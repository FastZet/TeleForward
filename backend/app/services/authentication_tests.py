"""Regression tests for administrator setup and login operations."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.user import User
from app.services import authentication as authentication_module
from app.services.authentication import AuthenticationService


@pytest.fixture
def session() -> MagicMock:
    value = MagicMock()
    value.scalar = AsyncMock()
    value.flush = AsyncMock()
    value.add = MagicMock()
    return value


@pytest.mark.asyncio
async def test_create_initial_admin_sets_superuser_and_setup_guard(
    session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session.scalar.side_effect = [None, None]
    monkeypatch.setattr(
        authentication_module, "hash_password", lambda value: "hashed"
    )

    user = await AuthenticationService(session).create_initial_admin(
        username="owner",
        email="owner@example.com",
        display_name="Owner",
        password="strong-password",
    )

    assert user.is_superuser is True
    assert user.password_hash == "hashed"
    assert session.add.call_count == 2
    assert session.flush.await_count == 2


@pytest.mark.asyncio
async def test_failed_login_increments_failure_count(
    session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        username="owner",
        password_hash="stored-hash",
        failed_login_attempts=2,
        is_active=True,
    )
    session.scalar.return_value = user
    monkeypatch.setattr(
        authentication_module, "verify_password", lambda *_args: False
    )

    result = await AuthenticationService(session).authenticate(
        "owner", "wrong-password"
    )

    assert result is None
    assert user.failed_login_attempts == 3
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_successful_login_clears_lockout(
    session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        username="owner",
        password_hash="stored-hash",
        failed_login_attempts=4,
        is_active=True,
    )
    session.scalar.return_value = user
    monkeypatch.setattr(
        authentication_module, "verify_password", lambda *_args: True
    )

    result = await AuthenticationService(session).authenticate(
        "owner", "correct-password"
    )

    assert result is user
    assert user.failed_login_attempts == 0
    assert user.locked_until is None
    assert user.last_login_at is not None

