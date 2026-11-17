"""Regression tests for encrypted Telegram API credential storage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.application_setting import ApplicationSetting
from app.services.telegram import credentials as credentials_module
from app.services.telegram.credentials import (
    TelegramCredentialsService,
)


@pytest.fixture
def session() -> MagicMock:
    value = MagicMock()
    value.scalar = AsyncMock()
    value.add = MagicMock()
    return value


@pytest.mark.asyncio
async def test_get_credentials_decrypts_hash_and_hides_it_from_repr(
    session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_id = ApplicationSetting(
        key="telegram.api_id", value=123, is_enabled=True
    )
    api_hash = ApplicationSetting(
        key="telegram.api_hash", value="encrypted", is_enabled=True
    )
    session.scalar.side_effect = [api_id, api_hash]
    monkeypatch.setattr(
        credentials_module, "decrypt_value", lambda value: "plain-secret"
    )

    result = await TelegramCredentialsService(session).get_credentials()

    assert result is not None
    assert result.api_id == 123
    assert result.api_hash == "plain-secret"
    assert "plain-secret" not in repr(result)


@pytest.mark.asyncio
async def test_set_credentials_encrypts_hash_and_marks_settings_private(
    session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session.scalar.side_effect = [None, None]
    monkeypatch.setattr(
        credentials_module,
        "encrypt_value",
        lambda value: f"ciphertext:{value}",
    )

    await TelegramCredentialsService(session).set_credentials(
        123, "plain-secret"
    )

    assert session.add.call_count == 2
    api_id, api_hash = (
        call.args[0] for call in session.add.call_args_list
    )
    assert api_id.key == "telegram.api_id"
    assert api_id.value == 123
    assert api_hash.key == "telegram.api_hash"
    assert api_hash.value == "ciphertext:plain-secret"
    assert api_hash.is_public is False


@pytest.mark.asyncio
async def test_get_credentials_returns_none_when_disabled(
    session: MagicMock,
) -> None:
    session.scalar.side_effect = [
        ApplicationSetting(key="telegram.api_id", value=123),
        ApplicationSetting(
            key="telegram.api_hash", value="encrypted", is_enabled=False
        ),
    ]

    assert await TelegramCredentialsService(session).get_credentials() is None


@pytest.mark.asyncio
async def test_clear_credentials_disables_both_settings(
    session: MagicMock,
) -> None:
    api_id = ApplicationSetting(key="telegram.api_id", value=123)
    api_hash = ApplicationSetting(
        key="telegram.api_hash", value="encrypted"
    )
    session.scalar.side_effect = [api_id, api_hash]

    await TelegramCredentialsService(session).clear_credentials()

    assert api_id.is_enabled is False
    assert api_hash.is_enabled is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("api_id", "api_hash"),
    [(0, "secret"), (True, "secret"), (123, "  ")],
)
async def test_set_credentials_rejects_invalid_values(
    session: MagicMock,
    api_id: int,
    api_hash: str,
) -> None:
    with pytest.raises(ValueError):
        await TelegramCredentialsService(session).set_credentials(
            api_id, api_hash
        )

    session.add.assert_not_called()

