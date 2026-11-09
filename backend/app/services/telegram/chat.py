"""
Telegram chat service.

Retrieves Telegram chat metadata and synchronises it with TeleForward's
persistent chat records.

Telegram chat IDs are stored as signed 64-bit integers because Telegram
uses identifiers that can exceed the range of a 32-bit integer.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import select
from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    ChatIdInvalidError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.tl.types import (
    Channel,
    Chat,
    User,
)

from app.models.telegram_chat import TelegramChat, TelegramChatType
from app.services.base import BaseService
from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TelegramChatInfo:
    """Normalised Telegram chat metadata."""

    telegram_chat_id: int
    title: str
    chat_type: str
    username: str | None
    description: str | None
    participant_count: int | None
    is_verified: bool
    is_restricted: bool
    is_scam: bool
    is_fake: bool


class TelegramChatService(BaseService):
    """
    Retrieve and synchronise Telegram chat metadata.

    Args:
        session: Asynchronous SQLAlchemy session.
        client_manager: Shared Telethon client manager.
    """

    def __init__(
        self,
        session,
        client_manager: TelegramClientManager,
    ) -> None:
        super().__init__(session)
        self.client_manager = client_manager

    async def get_chat_info(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int | str,
    ) -> TelegramChatInfo:
        """
        Retrieve metadata for a Telegram chat.

        chat_id may be a numeric Telegram ID or a public username.
        """
        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        entity = await self._resolve_entity(client, chat_id)

        return await self._normalise_entity(client, entity)

    async def sync_chat(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int | str,
    ) -> TelegramChat:
        """
        Retrieve Telegram metadata and persist the corresponding chat.

        The caller owns the database transaction.
        """
        info = await self.get_chat_info(
            account_id,
            api_id,
            api_hash,
            chat_id,
        )

        statement = select(TelegramChat).where(
            TelegramChat.account_id == account_id,
            TelegramChat.telegram_chat_id == info.telegram_chat_id,
        )

        chat = await self.session.scalar(statement)

        if chat is None:
            chat = TelegramChat(
                account_id=account_id,
                telegram_chat_id=info.telegram_chat_id,
            )
            self.session.add(chat)

        chat.title = info.title
        chat.username = info.username
        chat.chat_type = TelegramChatType(info.chat_type)
        chat.description = info.description
        chat.participant_count = info.participant_count
        chat.is_verified = info.is_verified
        chat.is_restricted = info.is_restricted
        chat.is_scam = info.is_scam
        chat.is_fake = info.is_fake

        await self.session.flush()

        self.logger.info(
            "telegram_chat_synchronised",
            account_id=account_id,
            telegram_chat_id=info.telegram_chat_id,
            chat_type=info.chat_type,
        )

        return chat

    async def list_account_chats(
        self,
        account_id: int,
        *,
        chat_type: TelegramChatType | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TelegramChat]:
        """List locally synchronised chats belonging to an account."""
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500.")

        if offset < 0:
            raise ValueError("offset cannot be negative.")

        statement = select(TelegramChat).where(
            TelegramChat.account_id == account_id
        )

        if chat_type is not None:
            statement = statement.where(
                TelegramChat.chat_type == chat_type
            )

        statement = (
            statement
            .order_by(TelegramChat.title.asc())
            .offset(offset)
            .limit(limit)
        )

        result = await self.session.scalars(statement)
        return list(result.all())

    async def delete_chat_record(
        self,
        account_id: int,
        chat_id: int,
    ) -> bool:
        """
        Delete a locally synchronised chat record.

        This does not leave or delete the Telegram conversation.
        """
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        statement = select(TelegramChat).where(
            TelegramChat.account_id == account_id,
            TelegramChat.id == chat_id,
        )

        chat = await self.session.scalar(statement)

        if chat is None:
            return False

        await self.session.delete(chat)
        await self.session.flush()

        self.logger.info(
            "telegram_chat_record_deleted",
            account_id=account_id,
            chat_record_id=chat_id,
        )

        return True

    async def _get_authorized_client(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramClient:
        """Retrieve a connected and authorised Telegram client."""
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        client = await self.client_manager.get_client(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            connect=True,
        )

        if not await client.is_user_authorized():
            raise PermissionError(
                "The Telegram account is not authorised."
            )

        return client

    @staticmethod
    async def _resolve_entity(
        client: TelegramClient,
        chat_id: int | str,
    ) -> User | Chat | Channel:
        """Resolve a Telegram identifier into a Telethon entity."""
        if isinstance(chat_id, str):
            identifier = chat_id.strip()

            if not identifier:
                raise ValueError("Chat identifier cannot be empty.")

            if identifier.startswith("@"):
                identifier = identifier[1:]

            try:
                entity = await client.get_entity(identifier)
            except (
                UsernameInvalidError,
                UsernameNotOccupiedError,
                ChannelPrivateError,
            ):
                raise

        elif isinstance(chat_id, int) and not isinstance(chat_id, bool):
            if chat_id == 0:
                raise ValueError("Telegram chat ID cannot be zero.")

            try:
                entity = await client.get_entity(chat_id)
            except (
                ChatIdInvalidError,
                ChannelPrivateError,
            ):
                raise

        else:
            raise ValueError("chat_id must be an integer or username.")

        if not isinstance(entity, (User, Chat, Channel)):
            raise ValueError("Unsupported Telegram entity type.")

        return entity

    @classmethod
    async def _normalise_entity(
        cls,
        client: TelegramClient,
        entity: User | Chat | Channel,
    ) -> TelegramChatInfo:
        """Convert a Telethon entity into normalised chat metadata."""
        if isinstance(entity, User):
            chat_type = "private"
            title = " ".join(
                part for part in (entity.first_name, entity.last_name)
                if part
            ) or str(entity.id)

            participant_count = None
            description = None

        elif isinstance(entity, Channel):
            if entity.megagroup:
                chat_type = "supergroup"
            elif entity.broadcast:
                chat_type = "channel"
            else:
                chat_type = "group"

            title = entity.title
            participant_count = None
            description = None

            try:
                full = await client.get_entity(entity)
                full_info = await client(
                    __import__(
                        "telethon.tl.functions.channels",
                        fromlist=["GetFullChannelRequest"],
                    ).GetFullChannelRequest(full)
                )
                participant_count = getattr(
                    full_info.full_chat,
                    "participants_count",
                    None,
                )
                description = getattr(
                    full_info.full_chat,
                    "about",
                    None,
                )
            except Exception:
                logger.debug(
                    "telegram_channel_full_metadata_unavailable",
                    telegram_chat_id=entity.id,
                    exc_info=True,
                )

        else:
            chat_type = "group"
            title = entity.title
            participant_count = getattr(
                entity,
                "participants_count",
                None,
            )
            description = None

        return TelegramChatInfo(
            telegram_chat_id=entity.id,
            title=title,
            chat_type=chat_type,
            username=getattr(entity, "username", None),
            description=description,
            participant_count=participant_count,
            is_verified=bool(getattr(entity, "verified", False)),
            is_restricted=bool(getattr(entity, "restricted", False)),
            is_scam=bool(getattr(entity, "scam", False)),
            is_fake=bool(getattr(entity, "fake", False)),
        )
