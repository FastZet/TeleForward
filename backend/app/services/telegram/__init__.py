"""
TeleForward Telegram services package.

Services are exposed through lazy imports to avoid loading every Telegram
integration module whenever a single service is imported.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_SERVICE_EXPORTS: dict[str, str] = {
    # Client and authentication
    "TelegramClientManager": ".client",
    "TelegramAuthService": ".auth",
    "TelegramAccountService": ".account",
    "TelegramSessionService": ".session",
    "TelegramConnectionService": ".connection",
    "TelegramHealthService": ".health",

    # Dialogs, chats and messages
    "TelegramDialogService": ".dialog",
    "TelegramChatService": ".chat",
    "TelegramMessageService": ".message",
    "TelegramMediaService": ".media",
    "TelegramSearchService": ".search",
    "TelegramReadService": ".read",

    # Participants and permissions
    "TelegramPermissionService": ".permissions",
    "TelegramParticipantService": ".participant",
    "TelegramInvitationService": ".invitation",
    "TelegramContactsService": ".contacts",
    "TelegramPrivacyService": ".privacy",
    "TelegramBlockService": ".block",
    "TelegramMuteService": ".mute",

    # Message delivery and management
    "TelegramForwardingService": ".forwarding",
    "TelegramCopyService": ".copy",
    "TelegramAlbumService": ".album",
    "TelegramEditService": ".edit",
    "TelegramDeleteService": ".delete",
    "TelegramPinService": ".pins",
    "TelegramReactionService": ".reactions",

    # Media transfer
    "TelegramDownloadService": ".download",
    "TelegramUploadService": ".upload",
    "TelegramProfilePhotoService": ".profile_photo",

    # Profile and account information
    "TelegramProfileService": ".profile",
    "TelegramUsernameService": ".username",

    # Notifications and updates
    "TelegramUpdateService": ".updates",
    "TelegramTypingService": ".typing",
    "TelegramNotificationService": ".notification",
}


__all__ = sorted(_SERVICE_EXPORTS)


def __getattr__(name: str) -> Any:
    """Load a Telegram service only when it is requested."""
    module_name = _SERVICE_EXPORTS.get(name)

    if module_name is None:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        )

    module = import_module(module_name, package=__name__)
    service = getattr(module, name)

    # Cache the resolved attribute for subsequent imports.
    globals()[name] = service

    return service


def __dir__() -> list[str]:
    """Expose lazy exports to IDEs and interactive inspection."""
    return sorted(
        set(globals()) | set(__all__)
    )
