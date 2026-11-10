"""
Telegram reactions service.

Provides reaction retrieval and updates through Telethon.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from telethon import TelegramClient, functions, types
from telethon.errors import (
    ChannelPrivateError,
    ChatIdInvalidError,
    MessageIdInvalidError,
    ReactionInvalidError,
)

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TelegramReaction:
    """Normalised message reaction information."""

    reaction: str
    count: int
    chosen_by_current_user: bool


@dataclass(frozen=True, slots=True)
class TelegramReactionSummary:
    """Reaction summary for a Telegram message."""

    chat_id: int
    message_id: int
    total_count: int
    reactions: list[TelegramReaction]


@dataclass(frozen=True, slots=True)
class TelegramReactor:
    """Normalised information about a user who reacted to a message."""

    user_id: int
    reaction: str
    date: Any | None


class TelegramReactionsService:
    """Retrieve and manage Telegram message reactions."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def get_reactions(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_id: int,
    ) -> TelegramReactionSummary:
        """Retrieve the reaction summary for a message."""
        self._validate_identifiers(
            account_id,
            chat_id,
            message_id,
        )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        message = await client.get_messages(
            chat_id,
            ids=message_id,
        )

        if message is None or isinstance(message, list):
            raise LookupError("Telegram message was not found.")

        raw_reactions = getattr(
            getattr(message, "reactions", None),
            "results",
            [],
        )

        reactions = [
            self._normalise_reaction(reaction)
            for reaction in raw_reactions
        ]

        total_count = sum(
            reaction.count
            for reaction in reactions
        )

        return TelegramReactionSummary(
            chat_id=chat_id,
            message_id=message_id,
            total_count=total_count,
            reactions=reactions,
        )

    async def set_reaction(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_id: int,
        reaction: str | None,
    ) -> None:
        """
        Set or remove the current account's reaction.

        Pass None to remove the current account's reaction.
        """
        self._validate_identifiers(
            account_id,
            chat_id,
            message_id,
        )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        entity = await client.get_input_entity(chat_id)

        reactions: list[types.Reaction] = []

        if reaction is not None:
            value = reaction.strip()

            if not value or len(value) > 64:
                raise ValueError(
                    "Reaction must contain 1–64 characters."
                )

            reactions = [
                types.ReactionEmoji(emoticon=value)
            ]

        try:
            await client(
                functions.messages.SendReactionRequest(
                    peer=entity,
                    msg_id=message_id,
                    reaction=reactions,
                )
            )
        except (
            ChannelPrivateError,
            ChatIdInvalidError,
            MessageIdInvalidError,
            ReactionInvalidError,
        ):
            raise

        logger.info(
            "telegram_reaction_updated",
            account_id=account_id,
            chat_id=chat_id,
            message_id=message_id,
            reaction=reaction,
            removed=reaction is None,
        )

    async def get_reactors(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_id: int,
        *,
        reaction: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TelegramReactor]:
        """
        Retrieve users who reacted to a message.

        Telegram may restrict reactor visibility depending on chat
        type, message settings, and account permissions.
        """
        self._validate_identifiers(
            account_id,
            chat_id,
            message_id,
        )

        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100.")

        if offset < 0:
            raise ValueError("offset cannot be negative.")

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        entity = await client.get_input_entity(chat_id)

        reaction_filter = None

        if reaction is not None:
            value = reaction.strip()

            if not value or len(value) > 64:
                raise ValueError(
                    "Reaction must contain 1–64 characters."
                )

            reaction_filter = types.ReactionEmoji(
                emoticon=value
            )

        try:
            result = await client(
                functions.messages.GetMessageReactionsListRequest(
                    peer=entity,
                    id=message_id,
                    reaction=reaction_filter,
                    offset=str(offset),
                    limit=limit,
                )
            )
        except (
            ChannelPrivateError,
            ChatIdInvalidError,
            MessageIdInvalidError,
        ):
            raise

        reactors: list[TelegramReactor] = []

        for reactor in getattr(result, "reactions", []):
            peer = getattr(reactor, "peer_id", None)

            if not isinstance(peer, types.PeerUser):
                continue

            reactors.append(
                TelegramReactor(
                    user_id=peer.user_id,
                    reaction=self._reaction_to_string(
                        getattr(reactor, "reaction", None)
                    ),
                    date=getattr(reactor, "date", None),
                )
            )

        return reactors

    async def _get_authorized_client(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramClient:
        """Retrieve an authorised Telegram client."""
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

    @classmethod
    def _normalise_reaction(
        cls,
        reaction: Any,
    ) -> TelegramReaction:
        """Convert a Telethon reaction count into a stable structure."""
        return TelegramReaction(
            reaction=cls._reaction_to_string(
                getattr(reaction, "reaction", None)
            ),
            count=int(getattr(reaction, "count", 0)),
            chosen_by_current_user=bool(
                getattr(reaction, "chosen_order", None) is not None
            ),
        )

    @staticmethod
    def _reaction_to_string(
        reaction: Any,
    ) -> str:
        """Convert a Telegram reaction object into a string."""
        if isinstance(reaction, types.ReactionEmoji):
            return reaction.emoticon

        if isinstance(reaction, types.ReactionCustomEmoji):
            return f"custom_emoji:{reaction.document_id}"

        if isinstance(reaction, types.ReactionPaid):
            return "paid"

        return "unknown"

    @staticmethod
    def _validate_identifiers(
        account_id: int,
        chat_id: int,
        message_id: int,
    ) -> None:
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")

        if message_id <= 0:
            raise ValueError("message_id must be positive.")
