"""
Telegram user-blocking service.

Supports:
- Blocking Telegram users.
- Unblocking Telegram users.
- Checking whether a user is blocked.
- Retrieving the blocked-user list.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import structlog
from telethon import TelegramClient, functions, types, utils
from telethon.errors import (
    FloodWaitError,
    PeerIdInvalidError,
    UserIdInvalidError,
)

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

DEFAULT_BLOCKED_USERS_LIMIT = 100
MAX_BLOCKED_USERS_LIMIT = 1000


@dataclass(frozen=True, slots=True)
class TelegramBlockedUser:
    """Information about a blocked Telegram user."""

    user_id: int
    access_hash: int | None
    first_name: str | None
    last_name: str | None
    username: str | None
    blocked_at: datetime | None


@dataclass(frozen=True, slots=True)
class TelegramBlockResult:
    """Result of a block or unblock operation."""

    user_id: int
    is_blocked: bool
    successful: bool


@dataclass(frozen=True, slots=True)
class TelegramBlockedUsersResult:
    """Paginated blocked-user listing."""

    users: tuple[TelegramBlockedUser, ...]
    total_returned: int
    offset: int
    limit: int


class TelegramBlockService:
    """Manage blocked users for a Telegram account."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def block_user(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        user_id: int,
    ) -> TelegramBlockResult:
        """Block a Telegram user."""
        self._validate_identifiers(account_id, user_id)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        input_user = await self._resolve_input_user(
            client,
            user_id,
        )

        try:
            await client(
                functions.contacts.BlockRequest(
                    id=input_user,
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_user_block_flood_wait",
                account_id=account_id,
                user_id=user_id,
            )
            raise

        except (
            PeerIdInvalidError,
            UserIdInvalidError,
        ):
            logger.exception(
                "telegram_user_block_failed",
                account_id=account_id,
                user_id=user_id,
            )
            raise

        logger.info(
            "telegram_user_blocked",
            account_id=account_id,
            user_id=user_id,
        )

        return TelegramBlockResult(
            user_id=user_id,
            is_blocked=True,
            successful=True,
        )

    async def unblock_user(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        user_id: int,
    ) -> TelegramBlockResult:
        """Unblock a Telegram user."""
        self._validate_identifiers(account_id, user_id)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        input_user = await self._resolve_input_user(
            client,
            user_id,
        )

        try:
            await client(
                functions.contacts.UnblockRequest(
                    id=input_user,
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_user_unblock_flood_wait",
                account_id=account_id,
                user_id=user_id,
            )
            raise

        except (
            PeerIdInvalidError,
            UserIdInvalidError,
        ):
            logger.exception(
                "telegram_user_unblock_failed",
                account_id=account_id,
                user_id=user_id,
            )
            raise

        logger.info(
            "telegram_user_unblocked",
            account_id=account_id,
            user_id=user_id,
        )

        return TelegramBlockResult(
            user_id=user_id,
            is_blocked=False,
            successful=True,
        )

    async def is_user_blocked(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        user_id: int,
    ) -> bool:
        """Check whether a Telegram user is blocked."""
        self._validate_identifiers(account_id, user_id)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            response = await client(
                functions.contacts.GetBlockedRequest(
                    offset=0,
                    limit=MAX_BLOCKED_USERS_LIMIT,
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_block_status_check_flood_wait",
                account_id=account_id,
                user_id=user_id,
            )
            raise

        blocked_users = getattr(
            response,
            "blocked",
            [],
        )

        return any(
            self._extract_user_id(item.peer) == user_id
            for item in blocked_users
        )

    async def get_blocked_users(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        *,
        offset: int = 0,
        limit: int = DEFAULT_BLOCKED_USERS_LIMIT,
    ) -> TelegramBlockedUsersResult:
        """Retrieve a page of blocked Telegram users."""
        if offset < 0:
            raise ValueError("offset cannot be negative.")

        if not 1 <= limit <= MAX_BLOCKED_USERS_LIMIT:
            raise ValueError(
                f"limit must be between 1 and "
                f"{MAX_BLOCKED_USERS_LIMIT}."
            )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            response = await client(
                functions.contacts.GetBlockedRequest(
                    offset=offset,
                    limit=limit,
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_blocked_users_list_flood_wait",
                account_id=account_id,
                offset=offset,
                limit=limit,
            )
            raise

        users_by_id = {
            user.id: user
            for user in getattr(response, "users", [])
            if isinstance(user, types.User)
        }

        results: list[TelegramBlockedUser] = []

        for blocked in getattr(response, "blocked", []):
            user_id = self._extract_user_id(
                blocked.peer
            )

            if user_id is None:
                continue

            user = users_by_id.get(user_id)

            blocked_at = (
                datetime.fromtimestamp(
                    blocked.date,
                    tz=timezone.utc,
                )
                if getattr(blocked, "date", None)
                else None
            )

            results.append(
                TelegramBlockedUser(
                    user_id=user_id,
                    access_hash=(
                        user.access_hash
                        if user is not None
                        else None
                    ),
                    first_name=(
                        user.first_name
                        if user is not None
                        else None
                    ),
                    last_name=(
                        user.last_name
                        if user is not None
                        else None
                    ),
                    username=(
                        user.username
                        if user is not None
                        else None
                    ),
                    blocked_at=blocked_at,
                )
            )

        return TelegramBlockedUsersResult(
            users=tuple(results),
            total_returned=len(results),
            offset=offset,
            limit=limit,
        )

    async def _resolve_input_user(
        self,
        client: TelegramClient,
        user_id: int,
    ) -> types.InputUser:
        """Resolve a numeric user ID into Telegram's InputUser."""
        entity = await client.get_input_entity(user_id)

        try:
            input_user = utils.get_input_user(entity)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "The supplied identifier does not resolve to a Telegram user."
            ) from exc

        if not isinstance(input_user, types.InputUser):
            raise ValueError(
                "The supplied identifier does not resolve to a Telegram user."
            )

        return input_user

    @staticmethod
    def _extract_user_id(
        peer: object,
    ) -> int | None:
        """Extract a user ID from a Telegram peer."""
        if isinstance(peer, types.PeerUser):
            return peer.user_id

        if isinstance(peer, types.InputPeerUser):
            return peer.user_id

        if isinstance(peer, types.InputUser):
            return peer.user_id

        return None

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

    @staticmethod
    def _validate_identifiers(
        account_id: int,
        user_id: int,
    ) -> None:
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if user_id <= 0:
            raise ValueError("user_id must be positive.")
