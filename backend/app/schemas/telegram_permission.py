
"""
TeleForward Telegram permission schemas.

Defines:
- Telegram permission categories.
- Chat administrator rights.
- Permission check requests.
- Individual permission results.
- Aggregate permission check responses.

These schemas describe permission information returned by Telegram.
Actual permission enforcement must be performed by the Telegram service.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.schemas.common import RequestSchema, ResponseSchema


class TelegramPermissionTypeSchema(StrEnum):
    """Telegram chat permission categories."""

    VIEW_MESSAGES = "view_messages"
    SEND_MESSAGES = "send_messages"
    SEND_MEDIA = "send_media"
    SEND_STICKERS = "send_stickers"
    SEND_GIFS = "send_gifs"
    SEND_POLLS = "send_polls"
    EMBED_LINKS = "embed_links"
    CHANGE_INFO = "change_info"
    INVITE_USERS = "invite_users"
    PIN_MESSAGES = "pin_messages"
    MANAGE_TOPICS = "manage_topics"
    DELETE_MESSAGES = "delete_messages"
    BAN_USERS = "ban_users"
    ADD_ADMINS = "add_admins"
    POST_MESSAGES = "post_messages"
    EDIT_MESSAGES = "edit_messages"
    MANAGE_CALLS = "manage_calls"
    ANONYMOUS_ADMIN = "anonymous_admin"


class TelegramParticipantRoleSchema(StrEnum):
    """Participant roles within a Telegram chat."""

    OWNER = "owner"
    ADMINISTRATOR = "administrator"
    MEMBER = "member"
    RESTRICTED = "restricted"
    LEFT = "left"
    BANNED = "banned"
    UNKNOWN = "unknown"


class TelegramPermissionCheckRequest(RequestSchema):
    """Request to inspect permissions for a Telegram chat."""

    account_id: int = Field(
        gt=0,
    )

    chat_id: int

    required_permissions: list[TelegramPermissionTypeSchema] = Field(
        min_length=1,
        max_length=20,
    )

    @staticmethod
    def _validate_unique_permissions(
        permissions: list[TelegramPermissionTypeSchema],
    ) -> None:
        if len(permissions) != len(set(permissions)):
            raise ValueError(
                "Required permissions must not contain duplicates"
            )

    def model_post_init(self, __context) -> None:
        self._validate_unique_permissions(self.required_permissions)


class TelegramChatPermissionResponse(ResponseSchema):
    """Permission information for one Telegram chat."""

    account_id: int

    chat_id: int

    participant_role: TelegramParticipantRoleSchema

    is_member: bool = False

    is_admin: bool = False

    is_creator: bool = False

    can_view_messages: bool = False

    can_send_messages: bool = False

    can_send_media: bool = False

    can_send_stickers: bool = False

    can_send_gifs: bool = False

    can_send_polls: bool = False

    can_embed_links: bool = False

    can_change_info: bool = False

    can_invite_users: bool = False

    can_pin_messages: bool = False

    can_manage_topics: bool = False

    can_delete_messages: bool = False

    can_ban_users: bool = False

    can_add_admins: bool = False

    can_post_messages: bool = False

    can_edit_messages: bool = False

    can_manage_calls: bool = False

    can_be_anonymous: bool = False

    checked_at: datetime


class TelegramPermissionResultSchema(ResponseSchema):
    """Result for one requested permission."""

    permission: TelegramPermissionTypeSchema

    granted: bool

    reason: str | None = Field(
        default=None,
        max_length=1000,
    )


class TelegramPermissionCheckResponse(ResponseSchema):
    """Aggregate result of a Telegram permission check."""

    account_id: int

    chat_id: int

    participant_role: TelegramParticipantRoleSchema

    is_member: bool

    all_permissions_granted: bool

    results: list[TelegramPermissionResultSchema] = Field(
        default_factory=list,
    )

    checked_at: datetime


class TelegramAdminRightsResponse(ResponseSchema):
    """Administrator rights granted to the current account."""

    account_id: int

    chat_id: int

    is_administrator: bool = False

    is_creator: bool = False

    can_change_info: bool = False

    can_delete_messages: bool = False

    can_ban_users: bool = False

    can_invite_users: bool = False

    can_pin_messages: bool = False

    can_add_admins: bool = False

    can_post_messages: bool = False

    can_edit_messages: bool = False

    can_manage_topics: bool = False

    can_manage_calls: bool = False

    can_be_anonymous: bool = False

    checked_at: datetime
