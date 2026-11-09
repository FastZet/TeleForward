
"""
TeleForward application exceptions.

Defines a centralised exception hierarchy for application,
authentication, database, Telegram, forwarding, scheduling,
and configuration errors.
"""


class TeleForwardError(Exception):
    """Base exception for all TeleForward application errors."""

    default_message = "An unexpected application error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details or {}

        super().__init__(self.message)


# ============================================================
# Configuration and infrastructure
# ============================================================

class ConfigurationError(TeleForwardError):
    """Application configuration is invalid or incomplete."""

    default_message = "Application configuration error."


class DatabaseError(TeleForwardError):
    """Database operation failed."""

    default_message = "A database operation failed."


class StorageError(TeleForwardError):
    """Persistent storage operation failed."""

    default_message = "A storage operation failed."


# ============================================================
# Authentication and authorisation
# ============================================================

class AuthenticationError(TeleForwardError):
    """Authentication failed or credentials are invalid."""

    default_message = "Authentication failed."


class AuthorizationError(TeleForwardError):
    """The authenticated user lacks the required permission."""

    default_message = "You are not authorised to perform this action."


class SessionError(AuthenticationError):
    """Session is invalid, expired, or unavailable."""

    default_message = "The session is invalid or has expired."


# ============================================================
# Validation and resource management
# ============================================================

class ValidationError(TeleForwardError):
    """Application-level validation failed."""

    default_message = "The supplied data is invalid."


class ResourceNotFoundError(TeleForwardError):
    """A requested application resource does not exist."""

    default_message = "The requested resource was not found."


class ResourceConflictError(TeleForwardError):
    """An operation conflicts with the current resource state."""

    default_message = "The requested operation conflicts with the current state."


class RateLimitExceededError(TeleForwardError):
    """An operation exceeded its permitted rate."""

    default_message = "Too many requests. Please try again later."


# ============================================================
# Telegram integration
# ============================================================

class TelegramError(TeleForwardError):
    """Base exception for Telegram integration errors."""

    default_message = "A Telegram operation failed."


class TelegramAuthenticationError(TelegramError):
    """Telegram account authentication failed."""

    default_message = "Telegram authentication failed."


class TelegramConnectionError(TelegramError):
    """Unable to establish or maintain a Telegram connection."""

    default_message = "Unable to connect to Telegram."


class TelegramFloodWaitError(TelegramError):
    """Telegram imposed a flood-wait restriction."""

    def __init__(
        self,
        retry_after: int,
        message: str | None = None,
    ) -> None:
        self.retry_after = max(0, retry_after)

        super().__init__(
            message or (
                f"Telegram rate limit reached. "
                f"Retry after {self.retry_after} seconds."
            ),
            details={"retry_after": self.retry_after},
        )


class TelegramAccountError(TelegramError):
    """A Telegram account is unavailable or in an invalid state."""

    default_message = "The Telegram account is unavailable."


# ============================================================
# Forwarding and processing
# ============================================================

class ForwardingError(TeleForwardError):
    """A message forwarding operation failed."""

    default_message = "Message forwarding failed."


class FilteringError(TeleForwardError):
    """Message filtering operation failed."""

    default_message = "Message filtering failed."


class TransformationError(TeleForwardError):
    """Message transformation operation failed."""

    default_message = "Message transformation failed."


class DuplicateMessageError(ForwardingError):
    """A message was identified as an existing duplicate."""

    default_message = "This message has already been processed."


# ============================================================
# Scheduling and background processing
# ============================================================

class SchedulingError(TeleForwardError):
    """A scheduled operation could not be created or executed."""

    default_message = "A scheduling operation failed."


class WorkerError(TeleForwardError):
    """A background worker encountered an error."""

    default_message = "A background worker operation failed."


class QueueError(TeleForwardError):
    """A queue operation failed."""

    default_message = "A queue operation failed."


# ============================================================
# Backup and restoration
# ============================================================

class BackupError(TeleForwardError):
    """Backup creation or export failed."""

    default_message = "Backup creation failed."


class RestoreError(TeleForwardError):
    """Backup validation or restoration failed."""

    default_message = "Backup restoration failed."
