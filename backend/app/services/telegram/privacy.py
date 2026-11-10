"""
Telegram privacy settings service.

Supports:
- Retrieving privacy rules.
- Updating privacy rules.
- Managing allowed and blocked users.
- Managing allowed and blocked chat participants.
- Supporting Telegram's standard privacy-rule types.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import structlog
from telethon import TelegramClient, functions, types, utils
from telethon.errors import FloodWaitError

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)


class PrivacyKey(StrEnum):
    """Supported Telegram privacy-setting keys."""

    STATUS_TIMESTAMP = "status_timestamp"
    CHAT_INVITE = "chat_invite"
    PHONE_CALL = "phone_call"
    PHONE_P2P = "phone_p2p"
    FORWARDS = "forwards"
    PROFILE_PHOTO = "profile_photo"
    PHONE_NUMBER = "phone_number"
    ADDED_BY_PHONE = "added_by_phone"
    ABOUT = "about"


class PrivacyRuleType(StrEnum):
    """Supported Telegram privacy-rule actions."""

    ALLOW_ALL = "allow_all"
    ALLOW_CONTACTS = "allow_contacts"
    ALLOW_CLOSE_FRIENDS = "allow_close_friends"
    ALLOW_USERS = "allow_users"
    ALLOW_CHAT_PARTICIPANTS = "allow_chat_participants"

    DISALLOW_ALL = "disallow_all"
    DISALLOW_CONTACTS = "disallow_contacts"
    DISALLOW_USERS = "disallow_users"
    DISALLOW_CHAT_PARTICIPANTS = "disallow_chat_participants"


@dataclass(frozen=True, slots=True)
class TelegramPrivacyRule:
    """Normalised Telegram privacy rule."""

    rule_type: PrivacyRuleType
    user_ids: tuple[int, ...] = ()
    chat_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class TelegramPrivacySettings:
    """Privacy settings associated with a Telegram account."""

    key: PrivacyKey
    rules: tuple[TelegramPrivacyRule, ...]


class TelegramPrivacyService:
    """Manage Telegram account privacy settings."""

    KEY_TYPES: dict[PrivacyKey, str] = {
        PrivacyKey.STATUS_TIMESTAMP: "InputPrivacyKeyStatusTimestamp",
        PrivacyKey.CHAT_INVITE: "InputPrivacyKeyChatInvite",
        PrivacyKey.PHONE_CALL: "InputPrivacyKeyPhoneCall",
        PrivacyKey.PHONE_P2P: "InputPrivacyKeyPhoneP2P",
        PrivacyKey.FORWARDS: "InputPrivacyKeyForwards",
        PrivacyKey.PROFILE_PHOTO: "InputPrivacyKeyProfilePhoto",
        PrivacyKey.PHONE_NUMBER: "InputPrivacyKeyPhoneNumber",
        PrivacyKey.ADDED_BY_PHONE: "InputPrivacyKeyAddedByPhone",
        PrivacyKey.ABOUT: "InputPrivacyKeyAbout",
    }

    RULE_TYPES: dict[str, PrivacyRuleType] = {
        "PrivacyValueAllowAll": PrivacyRuleType.ALLOW_ALL,
        "PrivacyValueAllowContacts": PrivacyRuleType.ALLOW_CONTACTS,
        "PrivacyValueAllowCloseFriends": PrivacyRuleType.ALLOW_CLOSE_FRIENDS,
        "PrivacyValueAllowUsers": PrivacyRuleType.ALLOW_USERS,
        "PrivacyValueAllowChatParticipants": (
            PrivacyRuleType.ALLOW_CHAT_PARTICIPANTS
        ),
        "PrivacyValueDisallowAll": PrivacyRuleType.DISALLOW_ALL,
        "PrivacyValueDisallowContacts": PrivacyRuleType.DISALLOW_CONTACTS,
        "PrivacyValueDisallowUsers": PrivacyRuleType.DISALLOW_USERS,
        "PrivacyValueDisallowChatParticipants": (
            PrivacyRuleType.DISALLOW_CHAT_PARTICIPANTS
        ),
    }

    RULE_CONSTRUCTORS: dict[PrivacyRuleType, str] = {
        PrivacyRuleType.ALLOW_ALL: "InputPrivacyValueAllowAll",
        PrivacyRuleType.ALLOW_CONTACTS: "InputPrivacyValueAllowContacts",
        PrivacyRuleType.ALLOW_CLOSE_FRIENDS: (
            "InputPrivacyValueAllowCloseFriends"
        ),
        PrivacyRuleType.ALLOW_USERS: "InputPrivacyValueAllowUsers",
        PrivacyRuleType.ALLOW_CHAT_PARTICIPANTS: (
            "InputPrivacyValueAllowChatParticipants"
        ),
        PrivacyRuleType.DISALLOW_ALL: "InputPrivacyValueDisallowAll",
        PrivacyRuleType.DISALLOW_CONTACTS: (
            "InputPrivacyValueDisallowContacts"
        ),
        PrivacyRuleType.DISALLOW_USERS: "InputPrivacyValueDisallowUsers",
        PrivacyRuleType.DISALLOW_CHAT_PARTICIPANTS: (
            "InputPrivacyValueDisallowChatParticipants"
        ),
    }

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def get_privacy_settings(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        key: PrivacyKey,
    ) -> TelegramPrivacySettings:
        """Retrieve privacy rules for a particular setting."""
        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        input_key = self._build_input_key(key)

        try:
            result = await client(
                functions.account.GetPrivacyRequest(
                    key=input_key,
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_privacy_retrieval_flood_wait",
                account_id=account_id,
                privacy_key=key.value,
            )
            raise

        rules = tuple(
            self._normalise_rule(rule)
            for rule in result.rules
            if type(rule).__name__ in self.RULE_TYPES
        )

        return TelegramPrivacySettings(
            key=key,
            rules=rules,
        )

    async def get_all_privacy_settings(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> dict[PrivacyKey, TelegramPrivacySettings]:
        """Retrieve all supported privacy settings."""
        settings: dict[PrivacyKey, TelegramPrivacySettings] = {}

        for key in PrivacyKey:
            try:
                settings[key] = await self.get_privacy_settings(
                    account_id,
                    api_id,
                    api_hash,
                    key,
                )

            except FloodWaitError:
                raise

            except Exception:
                logger.warning(
                    "telegram_privacy_setting_unavailable",
                    account_id=account_id,
                    privacy_key=key.value,
                    exc_info=True,
                )

        return settings

    async def set_privacy_settings(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        key: PrivacyKey,
        rules: list[TelegramPrivacyRule],
    ) -> TelegramPrivacySettings:
        """Replace the privacy rules for a particular setting."""
        if not rules:
            raise ValueError(
                "At least one privacy rule is required."
            )

        if len(rules) > 100:
            raise ValueError(
                "A maximum of 100 privacy rules is supported."
            )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        input_key = self._build_input_key(key)
        input_rules = await self._build_input_rules(
            client,
            rules,
        )

        try:
            await client(
                functions.account.SetPrivacyRequest(
                    key=input_key,
                    rules=input_rules,
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_privacy_update_flood_wait",
                account_id=account_id,
                privacy_key=key.value,
            )
            raise

        logger.info(
            "telegram_privacy_settings_updated",
            account_id=account_id,
            privacy_key=key.value,
            rule_count=len(rules),
        )

        return await self.get_privacy_settings(
            account_id,
            api_id,
            api_hash,
            key,
        )

    async def set_visibility(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        key: PrivacyKey,
        *,
        visibility: str,
    ) -> TelegramPrivacySettings:
        """
        Set a simple visibility policy.

        Supported values:
        - everyone
        - contacts
        - nobody
        """
        policies = {
            "everyone": [
                TelegramPrivacyRule(
                    PrivacyRuleType.ALLOW_ALL
                )
            ],
            "contacts": [
                TelegramPrivacyRule(
                    PrivacyRuleType.ALLOW_CONTACTS
                ),
                TelegramPrivacyRule(
                    PrivacyRuleType.DISALLOW_ALL
                ),
            ],
            "nobody": [
                TelegramPrivacyRule(
                    PrivacyRuleType.DISALLOW_ALL
                )
            ],
        }

        normalised_visibility = visibility.strip().lower()

        if normalised_visibility not in policies:
            raise ValueError(
                "visibility must be everyone, contacts or nobody."
            )

        return await self.set_privacy_settings(
            account_id,
            api_id,
            api_hash,
            key,
            policies[normalised_visibility],
        )

    async def allow_users(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        key: PrivacyKey,
        user_ids: list[int],
    ) -> TelegramPrivacySettings:
        """Allow specific users while preserving other existing rules."""
        if not user_ids:
            raise ValueError(
                "At least one user ID is required."
            )

        existing = await self.get_privacy_settings(
            account_id,
            api_id,
            api_hash,
            key,
        )

        rules = [
            rule
            for rule in existing.rules
            if rule.rule_type != PrivacyRuleType.ALLOW_USERS
        ]

        rules.append(
            TelegramPrivacyRule(
                rule_type=PrivacyRuleType.ALLOW_USERS,
                user_ids=tuple(dict.fromkeys(user_ids)),
            )
        )

        return await self.set_privacy_settings(
            account_id,
            api_id,
            api_hash,
            key,
            rules,
        )

    async def block_users(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        key: PrivacyKey,
        user_ids: list[int],
    ) -> TelegramPrivacySettings:
        """Exclude specific users from a privacy setting."""
        if not user_ids:
            raise ValueError(
                "At least one user ID is required."
            )

        existing = await self.get_privacy_settings(
            account_id,
            api_id,
            api_hash,
            key,
        )

        rules = [
            rule
            for rule in existing.rules
            if rule.rule_type != PrivacyRuleType.DISALLOW_USERS
        ]

        rules.append(
            TelegramPrivacyRule(
                rule_type=PrivacyRuleType.DISALLOW_USERS,
                user_ids=tuple(dict.fromkeys(user_ids)),
            )
        )

        return await self.set_privacy_settings(
            account_id,
            api_id,
            api_hash,
            key,
            rules,
        )

    @classmethod
    def _build_input_key(
        cls,
        key: PrivacyKey,
    ) -> Any:
        """Construct a Telethon input privacy key."""
        constructor_name = cls.KEY_TYPES.get(key)

        if constructor_name is None:
            raise ValueError(
                f"Unsupported privacy key: {key}"
            )

        constructor = getattr(types, constructor_name, None)

        if constructor is None:
            raise RuntimeError(
                f"Telethon does not support {constructor_name}."
            )

        return constructor()

    @classmethod
    def _normalise_rule(
        cls,
        rule: Any,
    ) -> TelegramPrivacyRule:
        """Convert a Telegram privacy rule into a normalised rule."""
        rule_type = cls.RULE_TYPES.get(type(rule).__name__)

        if rule_type is None:
            raise ValueError(
                f"Unsupported Telegram privacy rule: {type(rule).__name__}"
            )

        user_ids = tuple(
            getattr(user, "user_id", user)
            for user in getattr(rule, "users", [])
        )

        chat_ids = tuple(
            getattr(chat, "channel_id", getattr(chat, "chat_id", chat))
            for chat in getattr(rule, "chats", [])
        )

        return TelegramPrivacyRule(
            rule_type=rule_type,
            user_ids=user_ids,
            chat_ids=chat_ids,
        )

    @classmethod
    async def _build_input_rules(
        cls,
        client: TelegramClient,
        rules: list[TelegramPrivacyRule],
    ) -> list[Any]:
        """Construct Telethon input privacy rules."""
        input_rules: list[Any] = []

        for rule in rules:
            constructor_name = cls.RULE_CONSTRUCTORS.get(
                rule.rule_type
            )

            if constructor_name is None:
                raise ValueError(
                    f"Unsupported privacy rule: {rule.rule_type}"
                )

            constructor = getattr(
                types,
                constructor_name,
                None,
            )

            if constructor is None:
                raise RuntimeError(
                    f"Telethon does not support {constructor_name}."
                )

            if rule.rule_type in {
                PrivacyRuleType.ALLOW_USERS,
                PrivacyRuleType.DISALLOW_USERS,
            }:
                if not rule.user_ids:
                    raise ValueError(
                        f"{rule.rule_type.value} requires user IDs."
                    )

                users = []

                for user_id in rule.user_ids:
                    if user_id <= 0:
                        raise ValueError(
                            "User IDs must be positive."
                        )

                    entity = await client.get_entity(user_id)
                    users.append(utils.get_input_user(entity))

                input_rules.append(
                    constructor(users=users)
                )

            elif rule.rule_type in {
                PrivacyRuleType.ALLOW_CHAT_PARTICIPANTS,
                PrivacyRuleType.DISALLOW_CHAT_PARTICIPANTS,
            }:
                if not rule.chat_ids:
                    raise ValueError(
                        f"{rule.rule_type.value} requires chat IDs."
                    )

                chats = []

                for chat_id in rule.chat_ids:
                    if chat_id <= 0:
                        raise ValueError(
                            "Chat IDs must be positive."
                        )

                    entity = await client.get_entity(chat_id)
                    chats.append(utils.get_input_peer(entity))

                input_rules.append(
                    constructor(chats=chats)
                )

            else:
                if rule.user_ids or rule.chat_ids:
                    raise ValueError(
                        f"{rule.rule_type.value} does not accept IDs."
                    )

                input_rules.append(constructor())

        return input_rules

    async def _get_authorized_client(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramClient:
        """Retrieve an authorised Telegram client."""
        if account_id <= 0:
            raise ValueError(
                "account_id must be positive."
            )

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
