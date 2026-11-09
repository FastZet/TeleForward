
"""
TeleForward data export schemas.

Defines:
- Export formats and data categories.
- Export creation requests.
- Export job status responses.
- Export file metadata.
- Export listing and download information.

Export generation, access control, file retention, and cleanup
must be implemented by the export service.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.common import RequestSchema, ResponseSchema


class ExportFormat(StrEnum):
    """Supported export file formats."""

    JSON = "json"
    CSV = "csv"
    XLSX = "xlsx"


class ExportType(StrEnum):
    """Supported application data export categories."""

    MESSAGES = "messages"
    DELIVERIES = "deliveries"
    FORWARDING_RULES = "forwarding_rules"
    TELEGRAM_ACCOUNTS = "telegram_accounts"
    ANALYTICS = "analytics"
    AUDIT_LOGS = "audit_logs"
    CONFIGURATION = "configuration"


class ExportJobStatus(StrEnum):
    """Export job lifecycle states."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ExportSortOrder(StrEnum):
    """Export record ordering."""

    ASC = "asc"
    DESC = "desc"


class ExportCreateRequest(RequestSchema):
    """Request to create an export job."""

    export_type: ExportType

    format: ExportFormat = ExportFormat.JSON

    account_id: int | None = Field(
        default=None,
        gt=0,
    )

    forwarding_rule_id: int | None = Field(
        default=None,
        gt=0,
    )

    start_date: datetime | None = None

    end_date: datetime | None = None

    include_media: bool = False

    include_metadata: bool = True

    sort_order: ExportSortOrder = ExportSortOrder.ASC

    @model_validator(mode="after")
    def validate_export_request(self):
        """Validate export filters and date boundaries."""

        if self.start_date is not None:
            if self.start_date.tzinfo is None:
                raise ValueError(
                    "start_date must be timezone-aware"
                )

        if self.end_date is not None:
            if self.end_date.tzinfo is None:
                raise ValueError(
                    "end_date must be timezone-aware"
                )

        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date <= self.start_date
        ):
            raise ValueError(
                "end_date must be later than start_date"
            )

        if (
            self.include_media
            and self.export_type
            not in {
                ExportType.MESSAGES,
                ExportType.DELIVERIES,
            }
        ):
            raise ValueError(
                "Media can only be included in message or delivery exports"
            )

        if (
            self.forwarding_rule_id is not None
            and self.export_type
            not in {
                ExportType.MESSAGES,
                ExportType.DELIVERIES,
                ExportType.FORWARDING_RULES,
            }
        ):
            raise ValueError(
                "forwarding_rule_id is not applicable to this export type"
            )

        if (
            self.account_id is not None
            and self.export_type
            == ExportType.CONFIGURATION
        ):
            raise ValueError(
                "Account-specific configuration exports are not supported"
            )

        return self


class ExportJobResponse(ResponseSchema):
    """Export job status and progress."""

    id: int = Field(gt=0)

    export_type: ExportType

    format: ExportFormat

    status: ExportJobStatus

    progress_percent: float = Field(
        default=0,
        ge=0,
        le=100,
    )

    total_records: int | None = Field(
        default=None,
        ge=0,
    )

    processed_records: int = Field(
        default=0,
        ge=0,
    )

    error_message: str | None = Field(
        default=None,
        max_length=1000,
    )

    created_at: datetime

    started_at: datetime | None = None

    completed_at: datetime | None = None

    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_progress(self):
        """Validate export progress and lifecycle timestamps."""

        if (
            self.total_records is not None
            and self.processed_records > self.total_records
        ):
            raise ValueError(
                "processed_records cannot exceed total_records"
            )

        if (
            self.status == ExportJobStatus.COMPLETED
            and self.progress_percent != 100
        ):
            raise ValueError(
                "Completed exports must have 100 percent progress"
            )

        if (
            self.completed_at is not None
            and self.started_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError(
                "completed_at cannot precede started_at"
            )

        if (
            self.expires_at is not None
            and self.expires_at.tzinfo is None
        ):
            raise ValueError(
                "expires_at must be timezone-aware"
            )

        return self


class ExportFileResponse(ResponseSchema):
    """Metadata for a completed export file."""

    filename: str = Field(
        min_length=1,
        max_length=255,
    )

    format: ExportFormat

    content_type: str = Field(
        min_length=1,
        max_length=150,
    )

    file_size_bytes: int = Field(
        ge=0,
    )

    record_count: int = Field(
        ge=0,
    )

    checksum_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-fA-F0-9]{64}$",
    )

    created_at: datetime

    expires_at: datetime | None = None


class ExportDownloadResponse(ResponseSchema):
    """Authorised export download information."""

    export_id: int = Field(gt=0)

    download_url: str = Field(
        min_length=1,
        max_length=2048,
    )

    filename: str = Field(
        min_length=1,
        max_length=255,
    )

    expires_at: datetime


class ExportListResponse(ResponseSchema):
    """Paginated list of export jobs."""

    items: list[ExportJobResponse] = Field(
        default_factory=list,
    )

    total: int = Field(
        default=0,
        ge=0,
    )

    page: int = Field(
        default=1,
        ge=1,
    )

    page_size: int = Field(
        default=20,
        ge=1,
        le=100,
    )


class ExportCancelResponse(ResponseSchema):
    """Result of an export cancellation request."""

    export_id: int = Field(gt=0)

    status: ExportJobStatus

    cancelled_at: datetime
