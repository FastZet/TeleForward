"""Application handlers for persistent message-processing jobs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.chat import TelegramChat
from app.models.filter_rule import FilterRule
from app.models.forwarded_message import DeliveryStatus, ForwardedMessage
from app.models.forwarding_rule import ForwardingMode, ForwardingRule
from app.models.message import Message, MessageType
from app.models.processing_queue import (
    ProcessingQueue,
    QueueJobStatus,
    QueueJobType,
)
from app.models.telegram_account import TelegramAccount
from app.services.filtering.stored_rules import evaluate_stored_filters
from app.services.processing_queue_worker import QueueJobEnvelope
from app.services.telegram.album import TelegramAlbumService
from app.services.telegram.client import TelegramClientManager
from app.services.telegram.copy import TelegramCopyService
from app.services.telegram.credentials import TelegramCredentialsService
from app.services.telegram.forwarding import TelegramForwardingService
from app.services.telegram.edit import TelegramEditService
from app.services.telegram.delete import TelegramDeleteService
from app.services.transformations.base import (
    TransformationInput,
    TransformationStatus,
)
from app.services.transformations.engine import TransformationEngine
from app.services.transformations.prefix_suffix import PrefixSuffixTransformation
from app.services.transformations.registry import TransformationRegistry
from app.services.transformations.replace import ReplaceTransformation
from app.services.transformations.text import TextTransformation


class ForwardingJobError(RuntimeError):
    """Raised when a forwarding queue job cannot be delivered."""


class ProcessingQueueHandlers:
    """Handle queued forwarding work using persisted rules and filters.

    External Telegram delivery is at least once. A process crash after Telegram
    accepts a message but before the local delivery record commits can result
    in a duplicate on retry; Telegram offers no idempotency key for sends.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client_manager: TelegramClientManager,
        *,
        album_storage_dir: Path,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        if not isinstance(client_manager, TelegramClientManager):
            raise TypeError("client_manager must be a TelegramClientManager")
        self._session_factory = session_factory
        self._forwarder = TelegramForwardingService(client_manager)
        self._copier = TelegramCopyService(client_manager)
        self._album_copier = TelegramAlbumService(
            client_manager,
            album_storage_dir,
        )
        self._editor = TelegramEditService(client_manager)
        self._deleter = TelegramDeleteService(client_manager)

    async def forward_message(self, job: QueueJobEnvelope) -> None:
        """Evaluate a queued message against its rule and deliver it."""
        if job.job_type != QueueJobType.FORWARD_MESSAGE:
            raise TypeError("job must be a FORWARD_MESSAGE queue job")
        if job.forwarding_rule_id is None or job.message_id is None:
            raise ForwardingJobError("Forwarding job identifiers are missing")

        async with self._session_factory() as session:
            rule = await session.get(ForwardingRule, job.forwarding_rule_id)
            message = await session.get(Message, job.message_id)
            if rule is None or message is None:
                raise ForwardingJobError("Forwarding rule or message was not found")
            if (
                not rule.is_enabled
                or message.processing_status.value == "deleted"
            ):
                return

            source_chat = await session.get(TelegramChat, rule.source_chat_id)
            destination_chat = await session.get(
                TelegramChat,
                rule.destination_chat_id,
            )
            account = await session.get(
                TelegramAccount,
                rule.telegram_account_id,
            )
            self._validate_relationships(
                rule,
                message,
                source_chat,
                destination_chat,
                account,
            )

            filters = list(
                (
                    await session.scalars(
                        select(FilterRule)
                        .where(
                            FilterRule.forwarding_rule_id == rule.id,
                            FilterRule.is_enabled.is_(True),
                        )
                        .order_by(FilterRule.priority, FilterRule.id)
                    )
                ).all()
            )

            grouped_messages = [message]
            if rule.preserve_grouped_media and message.telegram_grouped_id is not None:
                grouped_messages = list(
                    (
                        await session.scalars(
                            select(Message)
                            .where(
                                Message.telegram_account_id
                                == message.telegram_account_id,
                                Message.source_chat_id == message.source_chat_id,
                                Message.telegram_grouped_id
                                == message.telegram_grouped_id,
                            )
                            .order_by(Message.telegram_message_id)
                        )
                    ).all()
                )
                if len(grouped_messages) < 2:
                    raise ForwardingJobError(
                        "Grouped message is incomplete in local storage"
                    )

            deliveries = await self._load_delivery_rows(
                session,
                rule,
                grouped_messages,
            )
            if self._is_already_terminal(deliveries, grouped_messages):
                return
            if any(
                item.delivery_status == DeliveryStatus.SENT
                for item in deliveries
            ):
                raise ForwardingJobError(
                    "Grouped delivery has a partial prior result and needs review"
                )
            if await self._has_active_delivery(
                session,
                rule.id,
                [item.id for item in grouped_messages],
                job.id,
            ):
                # Another queued job for an album owns the current attempt.
                return

            decisions = [
                evaluate_stored_filters(item, source_chat, filters)
                for item in grouped_messages
            ]
            now = datetime.now(UTC)
            if not all(decision.accepted for decision in decisions):
                for item, delivery in zip(
                    grouped_messages,
                    deliveries,
                    strict=True,
                ):
                    self._set_delivery_status(
                        delivery,
                        DeliveryStatus.SKIPPED,
                        now,
                        "Filtered",
                    )
                await session.commit()
                return

            credentials = await TelegramCredentialsService(
                session
            ).get_credentials()
            if credentials is None:
                raise ForwardingJobError(
                    "Telegram API credentials are not configured"
                )

            options = self._validated_options(rule.settings)
            transformed_texts: list[str] = []
            has_transformations = False
            for grouped_message in grouped_messages:
                transformed_text, has_transform = await self._transform_content(
                    rule.settings,
                    grouped_message,
                    source_chat,
                )
                if has_transform:
                    has_transformations = True
                    transformed_texts.append(transformed_text or "")
            if has_transformations and rule.mode == ForwardingMode.FORWARD:
                raise ForwardingJobError(
                    "Configured transformations require COPY mode"
                )
            for delivery in deliveries:
                delivery.delivery_status = DeliveryStatus.PROCESSING
                delivery.retry_count += 1
                delivery.last_attempt_at = now
                delivery.last_error = None
            await session.commit()

            internal_ids = [item.id for item in grouped_messages]
            telegram_ids = [
                item.telegram_message_id for item in grouped_messages
            ]
            try:
                destination_ids = await self._deliver(
                    rule=rule,
                    account_id=account.id,
                    api_id=credentials.api_id,
                    api_hash=credentials.api_hash,
                    source_chat_id=source_chat.telegram_chat_id,
                    destination_chat_id=destination_chat.telegram_chat_id,
                    messages=grouped_messages,
                    telegram_message_ids=telegram_ids,
                    options=options,
                    transformed_texts=(
                        transformed_texts if has_transformations else None
                    ),
                    has_transformations=has_transformations,
                )
                if len(destination_ids) != len(grouped_messages):
                    raise ForwardingJobError(
                        "Telegram returned an incomplete delivery result"
                    )
            except Exception as exc:
                await self._record_delivery_failure(
                    rule.id,
                    internal_ids,
                    exc,
                )
                raise

            await self._record_delivery_success(
                rule.id,
                internal_ids,
                destination_chat.id,
                destination_ids,
            )

    async def sync_message_edit(self, job: QueueJobEnvelope) -> None:
        """Apply an edited source text/caption to its sent destination copy."""
        rule, message, destination, account, delivery, credentials = (
            await self._load_sync_context(job)
        )
        if message.processing_status.value == "deleted":
            return
        if rule.settings.get("sync_edits") is not True:
            return
        if delivery.delivery_status != DeliveryStatus.SENT:
            return
        if delivery.destination_message_id is None:
            raise ForwardingJobError("Sent delivery has no destination message ID")
        content = message.text if message.message_type.value == "text" else message.caption
        text = content or ""
        if message.message_type.value == "text":
            await self._editor.edit_message(
                account.id,
                credentials.api_id,
                credentials.api_hash,
                destination.telegram_chat_id,
                delivery.destination_message_id,
                text,
                preserve_formatting=False,
            )
        else:
            await self._editor.edit_caption(
                account.id,
                credentials.api_id,
                credentials.api_hash,
                destination.telegram_chat_id,
                delivery.destination_message_id,
                text,
                preserve_formatting=False,
            )
        async with self._session_factory() as session:
            current = await session.get(ForwardedMessage, delivery.id)
            if current is not None:
                current.source_edit_at_delivery = message.edited_at or datetime.now(UTC)
                current.last_error = None
                await session.commit()

    async def sync_message_delete(self, job: QueueJobEnvelope) -> None:
        """Delete the destination copy when its source was deleted."""
        rule, _message, destination, account, delivery, credentials = (
            await self._load_sync_context(job)
        )
        if rule.settings.get("sync_deletes") is not True:
            return
        if delivery.delivery_status != DeliveryStatus.SENT:
            return
        if delivery.destination_message_id is None:
            raise ForwardingJobError("Sent delivery has no destination message ID")
        result = await self._deleter.delete_message(
            account.id,
            credentials.api_id,
            credentials.api_hash,
            destination.telegram_chat_id,
            delivery.destination_message_id,
            revoke=True,
        )
        if not result.successful:
            raise ForwardingJobError("Telegram could not delete a forwarded message")
        async with self._session_factory() as session:
            current = await session.get(ForwardedMessage, delivery.id)
            if current is not None:
                current.delivery_status = DeliveryStatus.CANCELLED
                current.last_error = None
                await session.commit()

    async def _load_sync_context(self, job: QueueJobEnvelope):
        if job.job_type not in {QueueJobType.SYNC_EDIT, QueueJobType.SYNC_DELETE}:
            raise TypeError("job must be a SYNC_EDIT or SYNC_DELETE queue job")
        if job.forwarding_rule_id is None or job.message_id is None:
            raise ForwardingJobError("Synchronization job identifiers are missing")
        async with self._session_factory() as session:
            rule = await session.get(ForwardingRule, job.forwarding_rule_id)
            message = await session.get(Message, job.message_id)
            if rule is None or message is None:
                raise ForwardingJobError("Rule or source message was not found")
            destination = await session.get(TelegramChat, rule.destination_chat_id)
            account = await session.get(TelegramAccount, rule.telegram_account_id)
            delivery = await session.scalar(
                select(ForwardedMessage).where(
                    ForwardedMessage.forwarding_rule_id == rule.id,
                    ForwardedMessage.source_message_id == message.id,
                )
            )
            if destination is None or account is None or delivery is None:
                raise ForwardingJobError("Destination delivery context is incomplete")
            if not account.is_enabled or not destination.is_accessible:
                raise ForwardingJobError("Telegram account or destination is unavailable")
            if (
                message.telegram_account_id != rule.telegram_account_id
                or destination.telegram_account_id != rule.telegram_account_id
            ):
                raise ForwardingJobError("Synchronization ownership does not match")
            credentials = await TelegramCredentialsService(session).get_credentials()
            if credentials is None:
                raise ForwardingJobError("Telegram API credentials are not configured")
            return rule, message, destination, account, delivery, credentials

    async def _deliver(
        self,
        *,
        rule: ForwardingRule,
        account_id: int,
        api_id: int,
        api_hash: str,
        source_chat_id: int,
        destination_chat_id: int,
        messages: list[Message],
        telegram_message_ids: list[int],
        options: dict[str, bool],
        transformed_texts: list[str] | None = None,
        has_transformations: bool = False,
    ) -> tuple[int, ...]:
        if rule.mode == ForwardingMode.FORWARD:
            results = await self._forwarder.forward_messages(
                account_id=account_id,
                api_id=api_id,
                api_hash=api_hash,
                source_chat_id=source_chat_id,
                destination_chat_id=destination_chat_id,
                message_ids=telegram_message_ids,
                silent=options["silent"],
                drop_author=options["drop_author"],
                drop_media_captions=options["drop_media_captions"],
            )
            return tuple(
                destination_id
                for result in results
                for destination_id in result.destination_message_ids
            )

        if rule.mode != ForwardingMode.COPY:
            raise ForwardingJobError("Forwarding mode is invalid")

        if len(messages) > 1:
            result = await self._album_copier.copy_album(
                account_id=account_id,
                api_id=api_id,
                api_hash=api_hash,
                source_chat_id=source_chat_id,
                destination_chat_id=destination_chat_id,
                message_ids=telegram_message_ids,
                silent=options["silent"],
                formatting_entities=(
                    options["formatting_entities"] and not has_transformations
                ),
                caption_overrides=(
                    dict(zip(telegram_message_ids, transformed_texts, strict=True))
                    if transformed_texts is not None
                    else None
                ),
            )
            return result.destination_message_ids

        result = await self._copier.copy_message(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            source_chat_id=source_chat_id,
            destination_chat_id=destination_chat_id,
            message_id=telegram_message_ids[0],
            silent=options["silent"],
            formatting_entities=(
                options["formatting_entities"] and not has_transformations
            ),
            text_override=(
                transformed_texts[0]
                if transformed_texts is not None
                else None
            ),
        )
        return result.destination_message_ids

    async def _transform_content(
        self,
        settings: Any,
        message: Message,
        source_chat: TelegramChat,
    ) -> tuple[str | None, bool]:
        """Run the allowlisted message transformation pipeline, if configured."""
        specifications = settings.get("transformations", [])
        if not specifications:
            return None, False
        if not isinstance(specifications, list) or len(specifications) > 20:
            raise ForwardingJobError(
                "Transformations must be a list of at most 20 entries"
            )
        constructors = {
            "text": TextTransformation,
            "prefix_suffix": PrefixSuffixTransformation,
            "replace": ReplaceTransformation,
        }
        registry = TransformationRegistry()
        names: list[str] = []
        for spec in specifications:
            if not isinstance(spec, Mapping) or set(spec) - {"name", "options"}:
                raise ForwardingJobError("Transformation configuration is invalid")
            name = spec.get("name")
            options = spec.get("options", {})
            if not isinstance(name, str) or name not in constructors:
                raise ForwardingJobError("Transformation name is unsupported")
            if not isinstance(options, Mapping):
                raise ForwardingJobError("Transformation options must be a mapping")
            if name in names:
                raise ForwardingJobError("Duplicate transformations are not allowed")
            try:
                transformation = constructors[name](**dict(options))
                registry.register(transformation)
            except (TypeError, ValueError) as exc:
                raise ForwardingJobError(
                    "Transformation configuration is invalid"
                ) from exc
            names.append(name)

        media_type = None
        if isinstance(message.media_metadata, Mapping):
            raw_media_type = message.media_metadata.get("media_type")
            if isinstance(raw_media_type, str):
                media_type = raw_media_type
        transformation_input = TransformationInput(
            message_id=message.telegram_message_id,
            account_id=message.telegram_account_id,
            chat_id=message.source_chat_id,
            text=message.text or "",
            caption=message.caption or "",
            media_type=media_type,
            sender_id=(
                message.sender_id
                if message.sender_id is not None and message.sender_id > 0
                else None
            ),
            metadata={
                "source_chat_id": source_chat.telegram_chat_id,
                "source_chat_title": source_chat.title,
                "source_message_id": message.telegram_message_id,
                "source_date": message.telegram_date.isoformat(),
            },
        )
        summary = await TransformationEngine(registry).execute(
            transformation_input,
            transformation_names=names,
        )
        if summary.status == TransformationStatus.FAILED:
            raise ForwardingJobError("Message transformation failed")
        return (
            summary.transformed_text
            if message.message_type == MessageType.TEXT
            else summary.transformed_caption,
            True,
        )

    async def _load_delivery_rows(
        self,
        session: AsyncSession,
        rule: ForwardingRule,
        messages: list[Message],
    ) -> list[ForwardedMessage]:
        existing = list(
            (
                await session.scalars(
                    select(ForwardedMessage)
                    .where(
                        ForwardedMessage.forwarding_rule_id == rule.id,
                        ForwardedMessage.source_message_id.in_(
                            [item.id for item in messages]
                        ),
                    )
                    .with_for_update()
                )
            ).all()
        )
        by_source_id = {item.source_message_id: item for item in existing}
        deliveries: list[ForwardedMessage] = []
        for message in messages:
            delivery = by_source_id.get(message.id)
            if delivery is None:
                delivery = ForwardedMessage(
                    forwarding_rule_id=rule.id,
                    source_message_id=message.id,
                    destination_chat_id=rule.destination_chat_id,
                    delivery_status=DeliveryStatus.PENDING,
                    retry_count=0,
                )
                session.add(delivery)
                await session.flush()
            deliveries.append(delivery)
        return deliveries

    @staticmethod
    def _is_already_terminal(
        deliveries: list[ForwardedMessage],
        messages: list[Message],
    ) -> bool:
        if len(deliveries) != len(messages):
            return False
        return all(
            delivery.delivery_status
            in {DeliveryStatus.SENT, DeliveryStatus.SKIPPED, DeliveryStatus.CANCELLED}
            for delivery in deliveries
        )

    @staticmethod
    async def _has_active_delivery(
        session: AsyncSession,
        rule_id: int,
        message_ids: list[int],
        current_job_id: int,
    ) -> bool:
        """Check whether another leased queue job currently owns this group."""
        now = datetime.now(UTC)
        active_job_id = await session.scalar(
            select(ProcessingQueue.id)
            .where(
                ProcessingQueue.id != current_job_id,
                ProcessingQueue.forwarding_rule_id == rule_id,
                ProcessingQueue.message_id.in_(message_ids),
                ProcessingQueue.status == QueueJobStatus.PROCESSING,
                ProcessingQueue.locked_until > now,
            )
            .limit(1)
        )
        return active_job_id is not None

    @staticmethod
    def _set_delivery_status(
        delivery: ForwardedMessage,
        state: DeliveryStatus,
        now: datetime,
        reason: str,
    ) -> None:
        delivery.delivery_status = state
        delivery.last_attempt_at = now
        delivery.last_error = reason

    async def _record_delivery_failure(
        self,
        rule_id: int,
        message_ids: list[int],
        error: Exception,
    ) -> None:
        error_kind = type(error).__name__
        async with self._session_factory() as session:
            deliveries = list(
                (
                    await session.scalars(
                        select(ForwardedMessage).where(
                            ForwardedMessage.forwarding_rule_id == rule_id,
                            ForwardedMessage.source_message_id.in_(message_ids),
                        )
                    )
                ).all()
            )
            for delivery in deliveries:
                delivery.delivery_status = DeliveryStatus.FAILED
                delivery.last_error = error_kind
            await session.commit()

    async def _record_delivery_success(
        self,
        rule_id: int,
        message_ids: list[int],
        destination_chat_id: int,
        destination_ids: tuple[int, ...],
    ) -> None:
        async with self._session_factory() as session:
            deliveries = list(
                (
                    await session.scalars(
                        select(ForwardedMessage)
                        .where(
                            ForwardedMessage.forwarding_rule_id == rule_id,
                            ForwardedMessage.source_message_id.in_(message_ids),
                        )
                        .order_by(ForwardedMessage.source_message_id)
                    )
                ).all()
            )
            if len(deliveries) != len(message_ids):
                raise ForwardingJobError(
                    "Delivery records changed during Telegram send"
                )
            now = datetime.now(UTC)
            destination_by_source_id = dict(
                zip(message_ids, destination_ids, strict=True)
            )
            for delivery in deliveries:
                delivery.delivery_status = DeliveryStatus.SENT
                delivery.destination_chat_id = destination_chat_id
                delivery.destination_message_id = destination_by_source_id[
                    delivery.source_message_id
                ]
                delivery.delivered_at = now
                delivery.last_attempt_at = now
                delivery.last_error = None
            rule = await session.get(ForwardingRule, rule_id)
            if rule is not None:
                rule.last_run_at = now
                rule.last_error = None
            await session.commit()

    @staticmethod
    def _validate_relationships(
        rule: ForwardingRule,
        message: Message,
        source_chat: TelegramChat | None,
        destination_chat: TelegramChat | None,
        account: TelegramAccount | None,
    ) -> None:
        if source_chat is None or destination_chat is None or account is None:
            raise ForwardingJobError("Forwarding rule references missing records")
        if not account.is_enabled:
            raise ForwardingJobError("Telegram account is disabled")
        if (
            message.telegram_account_id != rule.telegram_account_id
            or message.source_chat_id != rule.source_chat_id
            or source_chat.telegram_account_id != rule.telegram_account_id
            or destination_chat.telegram_account_id != rule.telegram_account_id
        ):
            raise ForwardingJobError("Message, chat, and rule ownership do not match")
        if not source_chat.is_accessible or not destination_chat.is_accessible:
            raise ForwardingJobError("A forwarding chat is not accessible")

    @staticmethod
    def _validated_options(settings: Any) -> dict[str, bool]:
        if not isinstance(settings, Mapping):
            raise ForwardingJobError("Forwarding rule settings must be a mapping")
        supported = {
            "silent",
            "drop_author",
            "drop_media_captions",
            "formatting_entities",
            "transformations",
            "sync_edits",
            "sync_deletes",
        }
        unsupported = set(settings) - supported
        if unsupported:
            raise ForwardingJobError(
                "Forwarding rule contains unsupported settings"
            )
        defaults = {
            "silent": False,
            "drop_author": False,
            "drop_media_captions": False,
            "formatting_entities": True,
            "sync_edits": False,
            "sync_deletes": False,
        }
        for name, default in tuple(defaults.items()):
            value = settings.get(name, default)
            if not isinstance(value, bool):
                raise ForwardingJobError(
                    f"Forwarding setting {name!r} must be a boolean"
                )
            defaults[name] = value
        return defaults


