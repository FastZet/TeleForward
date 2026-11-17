"""Persist incoming Telegram messages and enqueue enabled forwarding rules."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.chat import TelegramChat
from app.models.forwarding_rule import ForwardingRule
from app.models.message import Message, MessageProcessingStatus, MessageType
from app.models.processing_queue import QueueJobType
from app.services.processing_queue import ProcessingQueueService
from app.services.telegram.updates import TelegramUpdate


_MEDIA_TYPES = {
    "photo": MessageType.PHOTO,
    "video": MessageType.VIDEO,
    "document": MessageType.DOCUMENT,
    "audio": MessageType.AUDIO,
    "voice": MessageType.VOICE,
    "video_note": MessageType.VIDEO_NOTE,
    "animation": MessageType.ANIMATION,
    "sticker": MessageType.STICKER,
    "poll": MessageType.POLL,
    "contact": MessageType.CONTACT,
    "location": MessageType.LOCATION,
}


class TelegramUpdateIngestionService:
    """Turn new-message callbacks into durable message and queue records.

    Message insertion and all forwarding jobs share one transaction. Repeated
    Telegram callbacks therefore cannot create duplicate message/job rows.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def handle_update(self, update: TelegramUpdate) -> int:
        """Persist one supported update; return how many jobs were enqueued.

        Edits and deletions need dedicated synchronization semantics and are
        deliberately ignored here. Each album member arrives as a new-message
        update; its grouped ID is persisted for album-aware queue handling.
        """
        if update.update_type != "new_message" or update.message is None:
            return 0
        if update.chat_id is None or update.message_id is None:
            return 0

        async with self._session_factory() as session:
            async with session.begin():
                chat = await session.scalar(
                    select(TelegramChat).where(
                        TelegramChat.telegram_account_id == update.account_id,
                        TelegramChat.telegram_chat_id == update.chat_id,
                        TelegramChat.is_accessible.is_(True),
                        TelegramChat.is_archived.is_(False),
                    )
                )
                if chat is None:
                    return 0

                message_id = await self._upsert_message(session, update, chat)
                rules = (
                    await session.scalars(
                        select(ForwardingRule).where(
                            ForwardingRule.telegram_account_id == update.account_id,
                            ForwardingRule.source_chat_id == chat.id,
                            ForwardingRule.is_enabled.is_(True),
                        )
                    )
                ).all()

                queue = ProcessingQueueService(session)
                enqueued = 0
                for rule in rules:
                    _job, inserted = await queue.enqueue(
                        QueueJobType.FORWARD_MESSAGE,
                        {"source_telegram_message_id": update.message_id},
                        deduplication_key=f"forward:{rule.id}:{message_id}",
                        forwarding_rule_id=rule.id,
                        message_id=message_id,
                    )
                    enqueued += int(inserted)
                return enqueued

    async def _upsert_message(
        self,
        session: AsyncSession,
        update: TelegramUpdate,
        chat: TelegramChat,
    ) -> int:
        source = update.message
        text = getattr(source, "message", None)
        if not isinstance(text, str):
            text = getattr(source, "text", None)
        if not isinstance(text, str):
            text = None

        media_type = self._media_type(source)
        message_type = _MEDIA_TYPES.get(media_type, MessageType.OTHER)
        if message_type == MessageType.OTHER and not getattr(source, "media", None):
            message_type = MessageType.TEXT
        date = getattr(source, "date", None)
        if not isinstance(date, datetime):
            date = datetime.now(timezone.utc)
        elif date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        else:
            date = date.astimezone(timezone.utc)

        media_metadata = {"media_type": media_type} if media_type else None
        digest = hashlib.sha256(
            f"{message_type.value}\\0{text or ''}\\0{media_type or ''}".encode("utf-8")
        ).hexdigest()
        values: dict[str, Any] = {
            "telegram_account_id": update.account_id,
            "source_chat_id": chat.id,
            "telegram_message_id": update.message_id,
            "telegram_grouped_id": update.grouped_id,
            "sender_id": getattr(source, "sender_id", None),
            "message_type": message_type,
            "text": text if message_type == MessageType.TEXT else None,
            "caption": text if message_type != MessageType.TEXT else None,
            "media_metadata": media_metadata,
            "telegram_date": date,
            "processing_status": MessageProcessingStatus.PENDING,
            "content_hash": digest,
        }
        dialect = session.bind.dialect.name  # type: ignore[union-attr]
        if dialect == "sqlite":
            statement = sqlite_insert(Message).values(**values)
        elif dialect == "postgresql":
            statement = pg_insert(Message).values(**values)
        else:
            raise RuntimeError(f"Message ingestion does not support {dialect!r}")
        statement = statement.on_conflict_do_nothing(
            index_elements=[
                Message.telegram_account_id,
                Message.source_chat_id,
                Message.telegram_message_id,
            ]
        ).returning(Message.id)
        inserted_id = (await session.execute(statement)).scalar_one_or_none()
        if inserted_id is not None:
            return inserted_id
        existing_id = await session.scalar(
            select(Message.id).where(
                Message.telegram_account_id == update.account_id,
                Message.source_chat_id == chat.id,
                Message.telegram_message_id == update.message_id,
            )
        )
        if existing_id is None:
            raise RuntimeError("Message upsert completed without a readable row")
        return existing_id

    @staticmethod
    def _media_type(message: object) -> str | None:
        explicit = getattr(message, "media_type", None)
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip().lower()
        for name in _MEDIA_TYPES:
            if getattr(message, name, None) is not None:
                return name
        media = getattr(message, "media", None)
        if media is None:
            return None
        kind = type(media).__name__.lower()
        for name in _MEDIA_TYPES:
            if name in kind:
                return name
        return "other"
