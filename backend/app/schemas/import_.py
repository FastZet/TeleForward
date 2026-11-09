
"""
TeleForward data import schemas.

Defines:
- Import formats and categories.
- Import creation requests.
- Import job lifecycle and progress.
- Validation and preview results.
- Record-level import outcomes.
- Import completion summaries.

File handling, parsing, validation, transactional behaviour,
and access control belong to the import service.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.common import RequestSchema, ResponseSchema


class ImportFormat(StrEnum):
    """Supported import file formats."""

    JSON = "json"
    CSV = "csv"
    XLSX = "xlsx"


class ImportType(StrEnum):
    """Supported application data import categories."""

    FORWARDING_RULES = "forwarding_rules"
    CLASSIFICATION_RULES = "classification_rules"
    FILTER_RULES = "filter_rules"
    TRANSFORMATIONS = "transformations"
    CONFIGURATION = "configuration"


class ImportJobStatus(StrEnum):
    """Import job lifecycle states."""

    PENDING = "pending"
    VALIDATING = "validating"
    READY = "ready"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImportConflictStrategy(StrEnum):
    """Behaviour when imported records conflict with existing records."""

    SKIP = "skip"
    REPLACE = "replace"
    FAIL = "fail"


class ImportRecordStatus(StrEnum):
    """Outcome for an individual imported record."""

    PENDING = "pending"
    VALID = "valid"
    IMPORTED = "imported"
    SKIPPED = "skipped"
    FAILED = "failed"


class ImportCreateRequest(RequestSchema):
    """Request to create an import job."""

    import_type: ImportType

    format: ImportFormat = ImportFormat.JSON

    upload_id: str = Field(
        min_length=1,
        max_length=255,
    )

    dry_run: bool = True

    conflict_strategy: ImportConflictStrategy = (
        ImportConflictStrategy.SKIP
    )

    validate_only: bool = False

    @model_validator(mode="after")
    def validate_import_options(self):
        """Validate import execution options."""

        if self.validate_only and not self.dry_run:
            raise ValueError(
                "validate_only requires dry_run to be enabled"
            )

        return self


class ImportValidationIssue(ResponseSchema):
    """Validation issue associated with an imported record."""

    record_number: int | None = Field(
        default=None,
        ge=1,
    )

    field: str | None = Field(
        default=None,
        max_length=255,
    )

    code: str = Field(
        min_length=1,
        max_length=100,
    )

    message: str = Field(
        min_length=1,
        max_length=1000,
    )

    is_error: bool = True


class ImportValidationSummary(ResponseSchema):
    """Summary of import-file validation."""

    valid: bool

    total_records: int = Field(
        default=0,
        ge=0,
    )

    valid_records: int = Field(
        default=0,
        ge=0,
    )

    invalid_records: int = Field(
        default=0,
        ge=0,
    )

    warning_count: int = Field(
        default=0,
        ge=0,
    )

    error_count: int = Field(
        default=0,
        ge=0,
    )

    issues: list[ImportValidationIssue] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def validate_counts(self):
        """Ensure validation counts are internally consistent."""

        if self.valid_records + self.invalid_records > self.total_records:
            raise ValueError(
                "Valid and invalid records cannot exceed total_records"
            )

        if self.valid and self.error_count > 0:
            raise ValueError(
                "A valid import cannot contain validation errors"
            )

        return self


class ImportJobResponse(ResponseSchema):
    """Import job status and progress."""

    id: int = Field(gt=0)

    import_type: ImportType

    format: ImportFormat

    status: ImportJobStatus

    dry_run: bool

    conflict_strategy: ImportConflictStrategy

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

    imported_records: int = Field(
        default=0,
        ge=0,
    )

    skipped_records: int = Field(
        default=0,
        ge=0,
    )

    failed_records: int = Field(
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

    @model_validator(mode="after")
    def validate_import_progress(self):
        """Validate import counts and lifecycle timestamps."""

        if (
            self.total_records is not None
            and self.processed_records > self.total_records
        ):
            raise ValueError(
                "processed_records cannot exceed total_records"
            )

        if (
            self.imported_records
            + self.skipped_records
            + self.failed_records
            > self.processed_records
        ):
            raise ValueError(
                "Import outcome counts cannot exceed processed_records"
            )

        if (
            self.status == ImportJobStatus.COMPLETED
            and self.progress_percent != 100
        ):
            raise ValueError(
                "Completed imports must have 100 percent progress"
            )

        if (
            self.completed_at is not None
            and self.started_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError(
                "completed_at cannot precede started_at"
            )

        return self


class ImportRecordResult(ResponseSchema):
    """Result of processing one imported record."""

    record_number: int = Field(
        ge=1,
    )

    status: ImportRecordStatus

    message: str | None = Field(
        default=None,
        max_length=1000,
    )

    imported_record_id: int | None = Field(
        default=None,
        gt=0,
    )

    issues: list[ImportValidationIssue] = Field(
        default_factory=list,
    )


class ImportPreviewResponse(ResponseSchema):
    """Preview of parsed and validated import data."""

    import_type: ImportType

    format: ImportFormat

    validation: ImportValidationSummary

    preview_records: list[dict[str, object]] = Field(
        default_factory=list,
        max_length=20,
    )

    generated_at: datetime


class ImportResultResponse(ResponseSchema):
    """Final import execution summary."""

    import_id: int = Field(gt=0)

    status: ImportJobStatus

    total_records: int = Field(
        default=0,
        ge=0,
    )

    imported_records: int = Field(
        default=0,
        ge=0,
    )

    skipped_records: int = Field(
        default=0,
        ge=0,
    )

    failed_records: int = Field(
        default=0,
        ge=0,
    )

    results: list[ImportRecordResult] = Field(
        default_factory=list,
    )

    started_at: datetime | None = None

    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_result_counts(self):
        """Ensure final outcome counts do not exceed the input."""

        outcome_total = (
            self.imported_records
            + self.skipped_records
            + self.failed_records
        )

        if outcome_total > self.total_records:
            raise ValueError(
                "Import outcome counts cannot exceed total_records"
            )

        if (
            self.status == ImportJobStatus.COMPLETED
            and self.failed_records > 0
        ):
            raise ValueError(
                "An import with failed records cannot have completed status"
            )

        if (
            self.status == ImportJobStatus.COMPLETED_WITH_ERRORS
            and self.failed_records == 0
        ):
            raise ValueError(
                "Completed-with-errors status requires failed records"
            )

        if (
            self.completed_at is not None
            and self.started_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError(
                "completed_at cannot precede started_at"
            )

        return self
