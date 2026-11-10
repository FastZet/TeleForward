"""
Telegram contacts service.

Supports:
- Listing contacts.
- Retrieving individual contacts.
- Searching contacts.
- Importing contacts.
- Deleting contacts.
- Checking contact membership.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from telethon import TelegramClient, functions, types, utils
from telethon.errors import FloodWaitError

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TelegramContact:
    """Normalised Telegram contact."""

    user_id: int
    access_hash: int | None
    first_name: str | None
    last_name: str | None
    username: str | None
    phone: str | None
    is_mutual: bool
    is_bot: bool
    is_verified: bool


@dataclass(frozen=True, slots=True)
class TelegramContactImportResult:
    """Result of importing a contact."""

    phone: str
    successful: bool
    user_id: int | None
    error: str | None = None


class TelegramContactsService:
    """Manage Telegram account contacts."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def get_contacts(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> tuple[TelegramContact, ...]:
        """Retrieve all contacts available to the account."""
        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            result = await client(
                functions.contacts.GetContactsRequest(
                    hash=0,
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_contacts_retrieval_flood_wait",
                account_id=account_id,
            )
            raise

        contacts = getattr(result, "users", [])

        return tuple(
            self._normalise_contact(user)
            for user in contacts
            if isinstance(user, types.User)
        )

    async def get_contact(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        user_id: int,
    ) -> TelegramContact | None:
        """Retrieve a contact by Telegram user ID."""
        if user_id <= 0:
            raise ValueError(
                "user_id must be positive."
            )

        contacts = await self.get_contacts(
            account_id,
            api_id,
            api_hash,
        )

        return next(
            (
                contact
                for contact in contacts
                if contact.user_id == user_id
            ),
            None,
        )

    async def search_contacts(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        query: str,
    ) -> tuple[TelegramContact, ...]:
        """Search the account's locally available Telegram contacts."""
        normalised_query = query.strip().casefold()

        if not normalised_query:
            raise ValueError(
                "Search query cannot be empty."
            )

        contacts = await self.get_contacts(
            account_id,
            api_id,
            api_hash,
        )

        return tuple(
            contact
            for contact in contacts
            if normalised_query in " ".join(
                value
                for value in (
                    contact.first_name,
                    contact.last_name,
                    contact.username,
                    contact.phone,
                )
                if value
            ).casefold()
        )

    async def import_contact(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        *,
        phone: str,
        first_name: str,
        last_name: str = "",
        client_id: int = 0,
    ) -> TelegramContactImportResult:
        """Import a contact using its phone number."""
        normalised_phone = phone.strip()
        normalised_first_name = first_name.strip()
        normalised_last_name = last_name.strip()

        if not normalised_phone:
            raise ValueError(
                "Phone number cannot be empty."
            )

        if not normalised_first_name:
            raise ValueError(
                "First name cannot be empty."
            )

        if client_id < 0:
            raise ValueError(
                "client_id cannot be negative."
            )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            result = await client(
                functions.contacts.ImportContactsRequest(
                    contacts=[
                        types.InputPhoneContact(
                            client_id=client_id,
                            phone=normalised_phone,
                            first_name=normalised_first_name,
                            last_name=normalised_last_name,
                        )
                    ]
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_contact_import_flood_wait",
                account_id=account_id,
            )
            raise

        imported_user = next(
            (
                user
                for user in getattr(result, "users", [])
                if isinstance(user, types.User)
            ),
            None,
        )

        if imported_user is None:
            logger.info(
                "telegram_contact_import_no_user_found",
                account_id=account_id,
            )

            return TelegramContactImportResult(
                phone=normalised_phone,
                successful=False,
                user_id=None,
                error="Telegram did not resolve the phone number to a user.",
            )

        logger.info(
            "telegram_contact_imported",
            account_id=account_id,
            user_id=imported_user.id,
        )

        return TelegramContactImportResult(
            phone=normalised_phone,
            successful=True,
            user_id=imported_user.id,
        )

    async def import_contacts(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        contacts: list[dict[str, str]],
    ) -> tuple[TelegramContactImportResult, ...]:
        """Import multiple contacts in a single Telegram request."""
        if not contacts:
            return ()

        if len(contacts) > 100:
            raise ValueError(
                "A maximum of 100 contacts can be imported per request."
            )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        input_contacts: list[types.InputPhoneContact] = []
        normalised_phones: dict[int, str] = {}

        for index, contact in enumerate(contacts):
            phone = contact.get("phone", "").strip()
            first_name = contact.get("first_name", "").strip()
            last_name = contact.get("last_name", "").strip()

            if not phone or not first_name:
                raise ValueError(
                    f"Contact at index {index} requires phone and first_name."
                )

            input_contacts.append(
                types.InputPhoneContact(
                    client_id=index,
                    phone=phone,
                    first_name=first_name,
                    last_name=last_name,
                )
            )

            normalised_phones[index] = phone

        try:
            result = await client(
                functions.contacts.ImportContactsRequest(
                    contacts=input_contacts,
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_bulk_contact_import_flood_wait",
                account_id=account_id,
                contact_count=len(input_contacts),
            )
            raise

        imported_users = {
            user.id: user
            for user in getattr(result, "users", [])
            if isinstance(user, types.User)
        }

        imported_by_client_id = {
            imported.client_id: imported.user_id
            for imported in getattr(result, "imported", [])
        }

        return tuple(
            TelegramContactImportResult(
                phone=phone,
                successful=(
                    client_id in imported_by_client_id
                    or (
                        imported_by_client_id.get(client_id)
                        in imported_users
                    )
                ),
                user_id=imported_by_client_id.get(client_id),
                error=(
                    None
                    if client_id in imported_by_client_id
                    else "Telegram did not import this contact."
                ),
            )
            for client_id, phone in normalised_phones.items()
        )

    async def delete_contact(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        user_id: int,
    ) -> bool:
        """Delete a contact by Telegram user ID."""
        if user_id <= 0:
            raise ValueError(
                "user_id must be positive."
            )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            entity = await client.get_entity(user_id)
            input_user = utils.get_input_user(entity)

            await client(
                functions.contacts.DeleteContactsRequest(
                    id=[input_user],
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_contact_delete_flood_wait",
                account_id=account_id,
                user_id=user_id,
            )
            raise

        logger.info(
            "telegram_contact_deleted",
            account_id=account_id,
            user_id=user_id,
        )

        return True

    async def delete_all_contacts(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> int:
        """Delete all contacts currently returned by Telegram."""
        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            result = await client(
                functions.contacts.GetContactsRequest(
                    hash=0,
                )
            )

            users = [
                user
                for user in getattr(result, "users", [])
                if isinstance(user, types.User)
            ]

            if not users:
                return 0

            input_users = [
                utils.get_input_user(user)
                for user in users
            ]

            await client(
                functions.contacts.DeleteContactsRequest(
                    id=input_users,
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_all_contacts_delete_flood_wait",
                account_id=account_id,
            )
            raise

        logger.info(
            "telegram_all_contacts_deleted",
            account_id=account_id,
            deleted_count=len(input_users),
        )

        return len(input_users)

    async def is_contact(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        user_id: int,
    ) -> bool:
        """Check whether a Telegram user is in the contact list."""
        contact = await self.get_contact(
            account_id,
            api_id,
            api_hash,
            user_id,
        )

        return contact is not None

    @staticmethod
    def _normalise_contact(
        user: types.User,
    ) -> TelegramContact:
        """Convert a Telethon user into a normalised contact."""
        return TelegramContact(
            user_id=user.id,
            access_hash=getattr(user, "access_hash", None),
            first_name=getattr(user, "first_name", None),
            last_name=getattr(user, "last_name", None),
            username=getattr(user, "username", None),
            phone=getattr(user, "phone", None),
            is_mutual=bool(
                getattr(user, "mutual_contact", False)
            ),
            is_bot=bool(
                getattr(user, "bot", False)
            ),
            is_verified=bool(
                getattr(user, "verified", False)
            ),
        )

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
