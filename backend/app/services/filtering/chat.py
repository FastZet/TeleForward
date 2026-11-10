"""
TeleForward chat filtering utilities.

Provides chat identification and matching operations independently
of Telegram client and database access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


MAX_CHAT_IDS = 10_000
MAX_CHAT_USERNAMES = 10_000
MAX_CHAT_TITLES = 10_000


@dataclass(frozen=True, slots=True)
class ChatContext:
    """Normalised Telegram chat information."""

    chat_id: int | None = None
    title: str | None = None
    username: str | None = None
    chat_type: str | None = None

    is_forum: bool = False
    is_broadcast: bool = False
    is_megagroup: bool = False
    is_verified: bool = False
    is_scam: bool = False
    is_fake: bool = False


@dataclass(frozen=True, slots=True)
class ChatMatchResult:
    """Result of chat filtering."""

    matched: bool
    chat_id: int | None
    reason: str


class ChatFilter:
    """Evaluate Telegram chat allowlists and blocklists."""

    @staticmethod
    def _validate_ids(
        chat_ids: Iterable[int],
    ) -> frozenset[int]:
        """Validate and normalise chat IDs."""
        if isinstance(chat_ids, (str, bytes)):
            raise TypeError("Chat IDs must be an iterable of integers.")

        values = tuple(chat_ids)

        if len(values) > MAX_CHAT_IDS:
            raise ValueError("Too many chat IDs supplied.")

        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value == 0
            for value in values
        ):
            raise ValueError("Every chat ID must be a non-zero integer.")

        return frozenset(values)

    @staticmethod
    def _normalise_username(username: str) -> str:
        """Normalise a Telegram chat username."""
        if not isinstance(username, str):
            raise TypeError("Chat username must be a string.")

        normalised = username.strip().lstrip("@")

        if not normalised:
            raise ValueError("Chat username cannot be empty.")

        return normalised.casefold()

    @classmethod
    def _validate_usernames(
        cls,
        usernames: Iterable[str],
    ) -> frozenset[str]:
        """Validate and normalise chat usernames."""
        if isinstance(usernames, (str, bytes)):
            raise TypeError("Chat usernames must be an iterable.")

        values = tuple(usernames)

        if len(values) > MAX_CHAT_USERNAMES:
            raise ValueError("Too many chat usernames supplied.")

        return frozenset(
            cls._normalise_username(username)
            for username in values
        )

    @staticmethod
    def _validate_strings(
        values: Iterable[str],
        *,
        maximum: int,
        field_name: str,
    ) -> frozenset[str]:
        """Validate and normalise a collection of strings."""
        if isinstance(values, (str, bytes)):
            raise TypeError(
                f"{field_name} must be an iterable of strings."
            )

        items = tuple(values)

        if len(items) > maximum:
            raise ValueError(f"Too many {field_name} supplied.")

        if any(
            not isinstance(value, str) or not value.strip()
            for value in items
        ):
            raise ValueError(
                f"Every {field_name} entry must be a non-empty string."
            )

        return frozenset(
            value.strip().casefold()
            for value in items
        )

    def matches_allowlist(
        self,
        chat: ChatContext,
        *,
        allowed_ids: Iterable[int] = (),
        allowed_usernames: Iterable[str] = (),
        allowed_titles: Iterable[str] = (),
        allowed_types: Iterable[str] = (),
    ) -> ChatMatchResult:
        """Check whether a chat belongs to an allowlist."""
        ids = self._validate_ids(allowed_ids)
        usernames = self._validate_usernames(allowed_usernames)

        titles = self._validate_strings(
            allowed_titles,
            maximum=MAX_CHAT_TITLES,
            field_name="chat titles",
        )

        types = self._validate_strings(
            allowed_types,
            maximum=100,
            field_name="chat types",
        )

        # An empty allowlist means unrestricted chat selection.
        if not ids and not usernames and not titles and not types:
            return ChatMatchResult(
                matched=True,
                chat_id=chat.chat_id,
                reason="No chat allowlist configured.",
            )

        if chat.chat_id is not None and chat.chat_id in ids:
            return ChatMatchResult(
                matched=True,
                chat_id=chat.chat_id,
                reason="Chat ID matched the allowlist.",
            )

        if (
            chat.username
            and self._normalise_username(chat.username) in usernames
        ):
            return ChatMatchResult(
                matched=True,
                chat_id=chat.chat_id,
                reason="Chat username matched the allowlist.",
            )

        if (
            chat.title
            and chat.title.strip().casefold() in titles
        ):
            return ChatMatchResult(
                matched=True,
                chat_id=chat.chat_id,
                reason="Chat title matched the allowlist.",
            )

        if (
            chat.chat_type
            and chat.chat_type.strip().casefold() in types
        ):
            return ChatMatchResult(
                matched=True,
                chat_id=chat.chat_id,
                reason="Chat type matched the allowlist.",
            )

        return ChatMatchResult(
            matched=False,
            chat_id=chat.chat_id,
            reason="Chat did not match the allowlist.",
        )

    def matches_blocklist(
        self,
        chat: ChatContext,
        *,
        blocked_ids: Iterable[int] = (),
        blocked_usernames: Iterable[str] = (),
        blocked_titles: Iterable[str] = (),
        blocked_types: Iterable[str] = (),
    ) -> ChatMatchResult:
        """Check whether a chat belongs to a blocklist."""
        ids = self._validate_ids(blocked_ids)
        usernames = self._validate_usernames(blocked_usernames)

        titles = self._validate_strings(
            blocked_titles,
            maximum=MAX_CHAT_TITLES,
            field_name="chat titles",
        )

        types = self._validate_strings(
            blocked_types,
            maximum=100,
            field_name="chat types",
        )

        if chat.chat_id is not None and chat.chat_id in ids:
            return ChatMatchResult(
                matched=True,
                chat_id=chat.chat_id,
                reason="Chat ID matched the blocklist.",
            )

        if (
            chat.username
            and self._normalise_username(chat.username) in usernames
        ):
            return ChatMatchResult(
                matched=True,
                chat_id=chat.chat_id,
                reason="Chat username matched the blocklist.",
            )

        if (
            chat.title
            and chat.title.strip().casefold() in titles
        ):
            return ChatMatchResult(
                matched=True,
                chat_id=chat.chat_id,
                reason="Chat title matched the blocklist.",
            )

        if (
            chat.chat_type
            and chat.chat_type.strip().casefold() in types
        ):
            return ChatMatchResult(
                matched=True,
                chat_id=chat.chat_id,
                reason="Chat type matched the blocklist.",
            )

        return ChatMatchResult(
            matched=False,
            chat_id=chat.chat_id,
            reason="Chat did not match the blocklist.",
        )

    def matches(
        self,
        chat: ChatContext,
        *,
        allowed_ids: Iterable[int] = (),
        allowed_usernames: Iterable[str] = (),
        allowed_types: Iterable[str] = (),
        blocked_ids: Iterable[int] = (),
        blocked_usernames: Iterable[str] = (),
        blocked_types: Iterable[str] = (),
        allow_forums: bool = True,
        allow_broadcasts: bool = True,
        allow_megagroups: bool = True,
        allow_verified: bool = True,
        allow_scam: bool = False,
        allow_fake: bool = False,
    ) -> ChatMatchResult:
        """
        Apply chat restrictions.

        Blocklist and exclusion policies take precedence over allowlists.
        """
        exclusions = (
            (not allow_forums and chat.is_forum, "Forum chats are excluded."),
            (
                not allow_broadcasts and chat.is_broadcast,
                "Broadcast channels are excluded.",
            ),
            (
                not allow_megagroups and chat.is_megagroup,
                "Megagroups are excluded.",
            ),
            (
                not allow_verified and chat.is_verified,
                "Verified chats are excluded.",
            ),
            (
                not allow_scam and chat.is_scam,
                "Chats marked as scam are excluded.",
            ),
            (
                not allow_fake and chat.is_fake,
                "Chats marked as fake are excluded.",
            ),
        )

        for excluded, reason in exclusions:
            if excluded:
                return ChatMatchResult(
                    matched=False,
                    chat_id=chat.chat_id,
                    reason=reason,
                )

        blocked = self.matches_blocklist(
            chat,
            blocked_ids=blocked_ids,
            blocked_usernames=blocked_usernames,
            blocked_types=blocked_types,
        )

        if blocked.matched:
            return ChatMatchResult(
                matched=False,
                chat_id=chat.chat_id,
                reason=blocked.reason,
            )

        allowed = self.matches_allowlist(
            chat,
            allowed_ids=allowed_ids,
            allowed_usernames=allowed_usernames,
            allowed_types=allowed_types,
        )

        return ChatMatchResult(
            matched=allowed.matched,
            chat_id=chat.chat_id,
            reason=allowed.reason,
        )
