
"""
TeleForward backup and restore schemas.

Defines:
- Backup formats and statuses.
- Backup creation requests.
- Backup metadata responses.
- Backup validation results.
- Restore operation requests and responses.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class BackupStatusSchema(StrEnum):
    """Lifecycle states of a backup operation."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BackupTypeSchema(StrEnum):
    """Supported backup scopes."""

    FULL = "full"
    DATABASE_ONLY = "database_only"
    CONFIGURATION_ONLY = "configuration_only"


class BackupFormatSchema(StrEnum):
    """Supported backup archive formats."""

    ZIP = "zip"
    TAR_GZ = "tar.gz"


class BackupCreateRequest(RequestSchema):
    """Request to create a new backup."""

    backup_type: BackupTypeSchema = BackupTypeSchema.FULL

    backup_format: BackupFormatSchema = BackupFormatSchema.TAR_GZ

    include_telegram_sessions: bool = False

    description: str | None = Field(
        default=None,
        max_length=500,
    )


class BackupResponse(ResponseSchema):
    """Backup metadata returned by the API."""

    id: int

    backup_type: BackupTypeSchema
    backup_format: BackupFormatSchema

    status: BackupStatusSchema

    file_name: str | None = None
    file_size: int | None = Field(
        default=None,
        ge=0,
    )

    checksum: str | None = None

    description: str | None = None

    error_message: str | None = None

    started_at: datetime | None = None
    completed_at: datetime | None = None

    created_at: datetime


class BackupSummaryResponse(ResponseSchema):
    """Compact backup representation for dashboard listings."""

    id: int

    backup_type: BackupTypeSchema
    status: BackupStatusSchema

    file_name: str | None = None
    file_size: int | None = Field(
        default=None,
        ge=0,
    )

    created_at: datetime
    completed_at: datetime | None = None


class BackupListQuery(RequestSchema):
    """Filtering parameters for backup listings."""

    backup_type: BackupTypeSchema | None = None
    status: BackupStatusSchema | None = None

    date_from: datetime | None = None
    date_to: datetime | None = None


class BackupValidationRequest(RequestSchema):
    """Request to validate an existing backup."""

    verify_checksum: bool = True
    verify_archive_integrity: bool = True
    verify_database_schema: bool = True


class BackupValidationResponse(ResponseSchema):
    """Result of validating a backup archive."""

    backup_id: int

    valid: bool

    checksum_valid: bool | None = None
    archive_integrity_valid: bool | None = None
    database_schema_valid: bool | None = None

    errors: list[str] = Field(
        default_factory=list,
    )

    validated_at: datetime


class BackupRestoreRequest(RequestSchema):
    """Request to restore an existing backup."""

    backup_id: int

    restore_database: bool = True
    restore_configuration: bool = True
    restore_telegram_sessions: bool = False

    confirm_destructive_restore: bool = False


class BackupRestoreResponse(ResponseSchema):
    """Result or status of a backup restoration operation."""

    backup_id: int

    status: BackupStatusSchema

    started_at: datetime | None = None
    completed_at: datetime | None = None

    message: str

    error_message: str | None = None
