"""Database-backed administrator setup and authentication operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.application_setting import ApplicationSetting
from app.models.user import User

_SETUP_GUARD_KEY = "system.initial_admin_created"
MAX_FAILED_LOGINS = 5
LOGIN_LOCKOUT = timedelta(minutes=15)


class InitialSetupUnavailable(RuntimeError):
    """Raised when initial administrator setup is already complete."""


class AuthenticationService:
    """Authenticate users and securely create the initial administrator."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def initial_setup_available(self) -> bool:
        guard = await self._session.scalar(
            select(ApplicationSetting).where(
                ApplicationSetting.key == _SETUP_GUARD_KEY
            )
        )
        if guard is not None and guard.is_enabled:
            return False
        user_id = await self._session.scalar(select(User.id).limit(1))
        return user_id is None

    async def create_initial_admin(
        self,
        *,
        username: str,
        email: str,
        display_name: str | None,
        password: str,
    ) -> User:
        """Create the sole initial superuser under a unique DB guard row."""
        if not await self.initial_setup_available():
            raise InitialSetupUnavailable

        guard = ApplicationSetting(
            key=_SETUP_GUARD_KEY,
            value=True,
            category="system",
            description="Initial administrator setup completion marker",
            is_enabled=True,
            is_public=False,
        )
        self._session.add(guard)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # Concurrent setup requests contend on the unique guard key.
            await self._session.rollback()
            raise InitialSetupUnavailable from exc

        user = User(
            username=username,
            email=email,
            display_name=display_name,
            password_hash=hash_password(password),
            is_active=True,
            is_superuser=True,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def authenticate(self, username: str, password: str) -> User | None:
        """Verify credentials; return ``None`` for every denied login."""
        user = await self._session.scalar(
            select(User).where(User.username == username)
        )
        now = datetime.now(UTC)
        locked_until = user.locked_until if user is not None else None
        if locked_until is not None and locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=UTC)

        if user is None or not user.is_active or (
            locked_until is not None and locked_until > now
        ):
            return None

        if not verify_password(password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= MAX_FAILED_LOGINS:
                user.locked_until = now + LOGIN_LOCKOUT
            await self._session.flush()
            return None

        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now
        await self._session.flush()
        return user

