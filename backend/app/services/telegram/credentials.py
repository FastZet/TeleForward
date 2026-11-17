"""Encrypted storage for credentials used by Telegram client services."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select

from app.core.security import decrypt_value, encrypt_value
from app.models.application_setting import ApplicationSetting
from app.services.base import BaseService

_API_ID_KEY = "telegram.api_id"
_API_HASH_KEY = "telegram.api_hash"


@dataclass(frozen=True, slots=True)
class TelegramCredentials:
    """Telegram API credentials; hide the hash from repr and logs."""

    api_id: int
    api_hash: str = field(repr=False)


class TelegramCredentialsService(BaseService):
    """Read and update the application's shared Telegram API credentials.

    API hashes are encrypted before being written to ``application_settings``.
    Transaction ownership remains with the caller so credential updates can
    participate in a larger transaction.
    """

    async def get_credentials(self) -> TelegramCredentials | None:
        """Return decrypted credentials, or ``None`` when not configured."""
        api_id_setting = await self._get_setting(_API_ID_KEY)
        api_hash_setting = await self._get_setting(_API_HASH_KEY)
        if api_id_setting is None or api_hash_setting is None:
            return None
        if not api_id_setting.is_enabled or not api_hash_setting.is_enabled:
            return None

        api_id = api_id_setting.value
        encrypted_hash = api_hash_setting.value
        if isinstance(api_id, bool) or not isinstance(api_id, int) or api_id <= 0:
            raise ValueError("Stored Telegram API ID is invalid")
        if not isinstance(encrypted_hash, str) or not encrypted_hash:
            raise ValueError("Stored Telegram API hash is invalid")

        return TelegramCredentials(
            api_id=api_id,
            api_hash=decrypt_value(encrypted_hash),
        )

    async def configuration_status(self) -> tuple[bool, bool]:
        """Return safe configured flags without decrypting the API hash."""
        api_id_setting = await self._get_setting(_API_ID_KEY)
        api_hash_setting = await self._get_setting(_API_HASH_KEY)
        api_id_configured = bool(
            api_id_setting is not None
            and api_id_setting.is_enabled
            and isinstance(api_id_setting.value, int)
            and not isinstance(api_id_setting.value, bool)
            and api_id_setting.value > 0
        )
        api_hash_configured = bool(
            api_hash_setting is not None
            and api_hash_setting.is_enabled
            and isinstance(api_hash_setting.value, str)
            and api_hash_setting.value
        )
        return api_id_configured, api_hash_configured

    async def set_credentials(self, api_id: int, api_hash: str) -> None:
        """Store valid credentials, encrypting the API hash at rest."""
        if isinstance(api_id, bool) or not isinstance(api_id, int) or api_id <= 0:
            raise ValueError("api_id must be a positive integer")
        if not isinstance(api_hash, str) or not api_hash.strip():
            raise ValueError("api_hash must be a non-empty string")

        await self._store_setting(
            _API_ID_KEY,
            api_id,
            description="Telegram application API ID",
        )
        await self._store_setting(
            _API_HASH_KEY,
            encrypt_value(api_hash),
            description="Encrypted Telegram application API hash",
        )

    async def clear_credentials(self) -> None:
        """Disable configured credentials without exposing secret values."""
        for key in (_API_ID_KEY, _API_HASH_KEY):
            setting = await self._get_setting(key)
            if setting is not None:
                setting.is_enabled = False

    async def _get_setting(self, key: str) -> ApplicationSetting | None:
        return await self.session.scalar(
            select(ApplicationSetting).where(ApplicationSetting.key == key)
        )

    async def _store_setting(
        self,
        key: str,
        value: int | str,
        *,
        description: str,
    ) -> None:
        setting = await self._get_setting(key)
        if setting is None:
            self.session.add(
                ApplicationSetting(
                    key=key,
                    value=value,
                    category="telegram",
                    description=description,
                    is_enabled=True,
                    is_public=False,
                )
            )
            return

        setting.value = value
        setting.category = "telegram"
        setting.description = description
        setting.is_enabled = True
        setting.is_public = False

