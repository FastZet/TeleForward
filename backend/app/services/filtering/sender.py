"""
TeleForward sender filtering utilities.

Provides sender identification and matching operations independently
of Telegram client and database access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


MAX_SENDER_IDS = 10_000
MAX_USERNAMES = 10_000


@dataclass(frozen=True, slots=True)
class SenderContext:
    """Normalised sender information."""

    sender_id: int | None = None
    username: str | None = None
    display_name: str | None = None
    is_bot: bool = False
    is_verified: bool = False
    is_premium: bool = False


@dataclass(frozen=True, slots=True)
class SenderMatchResult:
    """Result of sender filtering."""

    matched: bool
    sender_id: int | None
    reason: str


class SenderFilter:
    """Evaluate sender allowlists and blocklists."""

    @staticmethod
    def _normalise_username(username: str) -> str:
        """Normalise a Telegram username."""
        if not isinstance(username, str):
            raise TypeError("Username must be a string.")

        username = username.strip().lstrip("@")

        if not username:
            raise ValueError("Username cannot be empty.")

        return username.casefold()

    @staticmethod
    def _validate_ids(
        sender_ids: Iterable[int],
    ) -> frozenset[int]:
        """Validate and normalise sender IDs."""
        if isinstance(sender_ids, (str, bytes)):
            raise TypeError("Sender IDs must be an iterable of integers.")

        values = tuple(sender_ids)

        if len(values) > MAX_SENDER_IDS:
            raise ValueError("Too many sender IDs supplied.")

        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value == 0
            for value in values
        ):
            raise ValueError("Every sender ID must be a non-zero integer.")

        return frozenset(values)

    @classmethod
    def _validate_usernames(
        cls,
        usernames: Iterable[str],
    ) -> frozenset[str]:
        """Validate and normalise usernames."""
        if isinstance(usernames, (str, bytes)):
            raise TypeError("Usernames must be an iterable of strings.")

        values = tuple(usernames)

        if len(values) > MAX_USERNAMES:
            raise ValueError("Too many usernames supplied.")

        return frozenset(
            cls._normalise_username(username)
            for username in values
        )

    def matches_allowlist(
        self,
        sender: SenderContext,
        *,
        allowed_ids: Iterable[int] = (),
        allowed_usernames: Iterable[str] = (),
        allowed_display_names: Iterable[str] = (),
    ) -> SenderMatchResult:
        """Check whether a sender belongs to an allowlist."""
        ids = self._validate_ids(allowed_ids)
        usernames = self._validate_usernames(allowed_usernames)

        names = frozenset(
            name.strip().casefold()
            for name in allowed_display_names
            if isinstance(name, str) and name.strip()
        )

        # An empty allowlist means no sender restriction.
        if not ids and not usernames and not names:
            return SenderMatchResult(
                matched=True,
                sender_id=sender.sender_id,
                reason="No sender allowlist configured.",
            )

        if sender.sender_id is not None and sender.sender_id in ids:
            return SenderMatchResult(
                matched=True,
                sender_id=sender.sender_id,
                reason="Sender ID matched the allowlist.",
            )

        if (
            sender.username
            and self._normalise_username(sender.username) in usernames
        ):
            return SenderMatchResult(
                matched=True,
                sender_id=sender.sender_id,
                reason="Sender username matched the allowlist.",
            )

        if (
            sender.display_name
            and sender.display_name.strip().casefold() in names
        ):
            return SenderMatchResult(
                matched=True,
                sender_id=sender.sender_id,
                reason="Sender display name matched the allowlist.",
            )

        return SenderMatchResult(
            matched=False,
            sender_id=sender.sender_id,
            reason="Sender did not match the allowlist.",
        )

    def matches_blocklist(
        self,
        sender: SenderContext,
        *,
        blocked_ids: Iterable[int] = (),
        blocked_usernames: Iterable[str] = (),
        blocked_display_names: Iterable[str] = (),
    ) -> SenderMatchResult:
        """Check whether a sender belongs to a blocklist."""
        ids = self._validate_ids(blocked_ids)
        usernames = self._validate_usernames(blocked_usernames)

        names = frozenset(
            name.strip().casefold()
            for name in blocked_display_names
            if isinstance(name, str) and name.strip()
        )

        if sender.sender_id is not None and sender.sender_id in ids:
            return SenderMatchResult(
                matched=True,
                sender_id=sender.sender_id,
                reason="Sender ID matched the blocklist.",
            )

        if (
            sender.username
            and self._normalise_username(sender.username) in usernames
        ):
            return SenderMatchResult(
                matched=True,
                sender_id=sender.sender_id,
                reason="Sender username matched the blocklist.",
            )

        if (
            sender.display_name
            and sender.display_name.strip().casefold() in names
        ):
            return SenderMatchResult(
                matched=True,
                sender_id=sender.sender_id,
                reason="Sender display name matched the blocklist.",
            )

        return SenderMatchResult(
            matched=False,
            sender_id=sender.sender_id,
            reason="Sender did not match the blocklist.",
        )

    def matches(
        self,
        sender: SenderContext,
        *,
        allowed_ids: Iterable[int] = (),
        allowed_usernames: Iterable[str] = (),
        blocked_ids: Iterable[int] = (),
        blocked_usernames: Iterable[str] = (),
        allow_bots: bool = True,
        allow_verified: bool = True,
        allow_premium: bool = True,
    ) -> SenderMatchResult:
        """
        Apply sender restrictions.

        Blocklist takes precedence over allowlist.
        """
        if not allow_bots and sender.is_bot:
            return SenderMatchResult(
                matched=False,
                sender_id=sender.sender_id,
                reason="Bot senders are excluded.",
            )

        if not allow_verified and sender.is_verified:
            return SenderMatchResult(
                matched=False,
                sender_id=sender.sender_id,
                reason="Verified senders are excluded.",
            )

        if not allow_premium and sender.is_premium:
            return SenderMatchResult(
                matched=False,
                sender_id=sender.sender_id,
                reason="Premium senders are excluded.",
            )

        blocked = self.matches_blocklist(
            sender,
            blocked_ids=blocked_ids,
            blocked_usernames=blocked_usernames,
        )

        if blocked.matched:
            return SenderMatchResult(
                matched=False,
                sender_id=sender.sender_id,
                reason=blocked.reason,
            )

        allowed = self.matches_allowlist(
            sender,
            allowed_ids=allowed_ids,
            allowed_usernames=allowed_usernames,
        )

        return SenderMatchResult(
            matched=allowed.matched,
            sender_id=sender.sender_id,
            reason=allowed.reason,
        )
