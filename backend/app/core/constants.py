
"""
TeleForward application constants.

Central registry for application metadata, API defaults,
pagination limits, security parameters and operational values.

These are application defaults, not substitutes for
environment-specific configuration.
"""

from typing import Final


# ============================================================
# Application metadata
# ============================================================

APP_NAME: Final[str] = "TeleForward"
APP_VERSION: Final[str] = "0.1.0"
APP_DESCRIPTION: Final[str] = (
    "Self-hosted Telegram automation and message forwarding platform."
)


# ============================================================
# API configuration
# ============================================================

API_V1_PREFIX: Final[str] = "/api/v1"

API_HEALTH_ENDPOINT: Final[str] = "/health"
API_LIVENESS_ENDPOINT: Final[str] = "/health/live"
API_READINESS_ENDPOINT: Final[str] = "/health/ready"
API_DETAILED_HEALTH_ENDPOINT: Final[str] = "/health/details"

DEFAULT_PAGE: Final[int] = 1
DEFAULT_PAGE_SIZE: Final[int] = 20
MAX_PAGE_SIZE: Final[int] = 100

DEFAULT_REQUEST_TIMEOUT_SECONDS: Final[int] = 30


# ============================================================
# Security defaults
# ============================================================

MIN_PASSWORD_LENGTH: Final[int] = 12
MAX_PASSWORD_LENGTH: Final[int] = 128

MIN_SECRET_LENGTH: Final[int] = 32

CSRF_TOKEN_BYTES: Final[int] = 32

MAX_LOGIN_ATTEMPTS: Final[int] = 5
LOGIN_LOCKOUT_SECONDS: Final[int] = 900

DEFAULT_SESSION_MAX_AGE_SECONDS: Final[int] = 86400

REQUEST_ID_HEADER: Final[str] = "X-Request-ID"
CSRF_HEADER: Final[str] = "X-CSRF-Token"


# ============================================================
# Telegram integration
# ============================================================

TELEGRAM_DEFAULT_CONNECT_TIMEOUT: Final[int] = 15
TELEGRAM_DEFAULT_REQUEST_TIMEOUT: Final[int] = 30

TELEGRAM_MAX_RECONNECT_ATTEMPTS: Final[int] = 5

TELEGRAM_MIN_FLOOD_WAIT_SECONDS: Final[int] = 1

TELEGRAM_SESSION_EXTENSION: Final[str] = ".session"


# ============================================================
# Message processing
# ============================================================

DEFAULT_MESSAGE_BATCH_SIZE: Final[int] = 100
MAX_MESSAGE_BATCH_SIZE: Final[int] = 1000

DEFAULT_PROCESSING_CONCURRENCY: Final[int] = 5

DEFAULT_MAX_RETRY_ATTEMPTS: Final[int] = 5

DEFAULT_RETRY_DELAY_SECONDS: Final[int] = 5
MAX_RETRY_DELAY_SECONDS: Final[int] = 3600

DEFAULT_DUPLICATE_CHECK_ENABLED: Final[bool] = True


# ============================================================
# Background processing
# ============================================================

DEFAULT_WORKER_POLL_INTERVAL_SECONDS: Final[float] = 1.0

DEFAULT_WORKER_SHUTDOWN_TIMEOUT_SECONDS: Final[int] = 30

DEFAULT_SCHEDULER_MISFIRE_GRACE_SECONDS: Final[int] = 60

DEFAULT_JOB_MAX_INSTANCES: Final[int] = 1


# ============================================================
# Storage
# ============================================================

DEFAULT_BACKUP_RETENTION_COUNT: Final[int] = 10

DEFAULT_LOG_RETENTION_DAYS: Final[int] = 30

MAX_UPLOAD_SIZE_BYTES: Final[int] = 100 * 1024 * 1024

MAX_EXPORT_SIZE_BYTES: Final[int] = 500 * 1024 * 1024


# ============================================================
# Date and time
# ============================================================

DEFAULT_TIMEZONE: Final[str] = "Asia/Kolkata"

DATETIME_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%S%z"


# ============================================================
# Content types
# ============================================================

JSON_CONTENT_TYPE: Final[str] = "application/json"

OCTET_STREAM_CONTENT_TYPE: Final[str] = "application/octet-stream"


# ============================================================
# Application status identifiers
# ============================================================

STATUS_ACTIVE: Final[str] = "active"
STATUS_INACTIVE: Final[str] = "inactive"
STATUS_PENDING: Final[str] = "pending"
STATUS_RUNNING: Final[str] = "running"
STATUS_COMPLETED: Final[str] = "completed"
STATUS_FAILED: Final[str] = "failed"
STATUS_PAUSED: Final[str] = "paused"
STATUS_CANCELLED: Final[str] = "cancelled"


# ============================================================
# Message processing status identifiers
# ============================================================

MESSAGE_STATUS_PENDING: Final[str] = "pending"
MESSAGE_STATUS_PROCESSING: Final[str] = "processing"
MESSAGE_STATUS_FORWARDED: Final[str] = "forwarded"
MESSAGE_STATUS_SKIPPED: Final[str] = "skipped"
MESSAGE_STATUS_FAILED: Final[str] = "failed"


# ============================================================
# Logging
# ============================================================

DEFAULT_LOG_LEVEL: Final[str] = "INFO"

LOG_TIMESTAMP_FORMAT: Final[str] = "iso"


# ============================================================
# Feature defaults
# ============================================================

DEFAULT_FEATURE_FLAGS: Final[dict[str, bool]] = {
    "message_edit_sync": True,
    "message_delete_sync": True,
    "duplicate_prevention": True,
    "scheduled_forwarding": True,
    "backfill": True,
    "message_classification": True,
    "notifications": True,
}
