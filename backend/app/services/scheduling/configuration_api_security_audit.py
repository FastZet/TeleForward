
"""Audit logging for scheduling configuration API security."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

_MAX_EVENT_SIZE = 64 * 1024

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|secret|token|authorization|cookie|credential|"
    r"api[_-]?key|session[_-]?string|private[_-]?key)",
    re.IGNORECASE,
)

_SAFE_IDENTIFIER_PATTERN = re.compile(
    r"^[a-zA-Z0-9_.:@-]{1,128}$"
)


class SecurityAuditEventType(StrEnum):
    """Supported configuration API security audit events."""

    AUTHENTICATION_SUCCESS = "authentication_success"
    AUTHENTICATION_FAILURE = "authentication_failure"
    AUTHORIZATION_SUCCESS = "authorization_success"
    AUTHORIZATION_FAILURE = "authorization_failure"
    RATE_LIMIT_REJECTED = "rate_limit_rejected"
    REQUEST_REJECTED = "request_rejected"
    SECURITY_CONFIGURATION_CHANGED = "security_configuration_changed"
    SECURITY_INTEGRATION_INSTALLED = "security_integration_installed"
    SECURITY_INTEGRATION_FAILURE = "security_integration_failure"


@dataclass(frozen=True, slots=True)
class SecurityAuditEvent:
    """Immutable security audit event."""

    event_type: SecurityAuditEventType
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    event_id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )
    principal_id: str | None = None
    request_id: str | None = None
    method: str | None = None
    path: str | None = None
    source_ip: str | None = None
    success: bool = False
    reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate event fields."""

        if not isinstance(self.event_type, SecurityAuditEventType):
            raise TypeError(
                "event_type must be a SecurityAuditEventType"
            )

        if not isinstance(self.occurred_at, datetime):
            raise TypeError("occurred_at must be a datetime")

        if (
            self.occurred_at.tzinfo is None
            or self.occurred_at.utcoffset() is None
        ):
            raise ValueError(
                "occurred_at must be timezone-aware"
            )

        if not isinstance(self.event_id, str) or not _SAFE_IDENTIFIER_PATTERN.fullmatch(
            self.event_id
        ):
            raise ValueError("event_id is invalid")

        for field_name in (
            "principal_id",
            "request_id",
            "method",
            "path",
            "source_ip",
            "reason",
        ):
            value = getattr(self, field_name)

            if value is not None and not isinstance(value, str):
                raise TypeError(
                    f"{field_name} must be a string or None"
                )

        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean")

        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")

        object.__setattr__(
            self,
            "metadata",
            dict(self.metadata),
        )


class SecurityAuditError(RuntimeError):
    """Raised when a security audit operation fails."""


def _sanitize_value(
    value: Any,
    *,
    depth: int = 0,
) -> Any:
    """Convert supported values into JSON-safe audit data."""

    if depth > 12:
        return "[maximum nesting depth exceeded]"

    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        if not __import__("math").isfinite(value):
            return str(value)
        return value

    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "Naive datetimes cannot be written to the audit log"
            )

        return value.astimezone(timezone.utc).isoformat()

    if isinstance(value, StrEnum):
        return value.value

    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}

        for key, item in value.items():
            if not isinstance(key, str):
                continue

            if _SENSITIVE_KEY_PATTERN.search(key):
                sanitized[key] = "[REDACTED]"
                continue

            sanitized[key] = _sanitize_value(
                item,
                depth=depth + 1,
            )

        return sanitized

    if isinstance(value, (list, tuple)):
        return [
            _sanitize_value(item, depth=depth + 1)
            for item in value
        ]

    if isinstance(value, (set, frozenset)):
        sanitized_items = [
            _sanitize_value(item, depth=depth + 1)
            for item in value
        ]

        return sorted(
            sanitized_items,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                ensure_ascii=False,
            ),
        )

    return f"<unsupported:{type(value).__name__}>"


def _serialize_event(
    event: SecurityAuditEvent,
) -> str:
    """Serialize an event into a sanitized JSON line."""

    payload = {
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "occurred_at": event.occurred_at.astimezone(
            timezone.utc
        ).isoformat(),
        "principal_id": event.principal_id,
        "request_id": event.request_id,
        "method": event.method,
        "path": event.path,
        "source_ip": event.source_ip,
        "success": event.success,
        "reason": event.reason,
        "metadata": _sanitize_value(event.metadata),
    }

    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    if len(serialized.encode("utf-8")) > _MAX_EVENT_SIZE:
        raise SecurityAuditError(
            "Security audit event exceeds maximum size"
        )

    return serialized


class SecurityAuditLogger:
    """Thread-safe append-only security audit logger.

    This implementation is intended for a single application process.
    It does not provide cross-process file locking or tamper-proof
    audit storage.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        max_file_size_bytes: int = 50 * 1024 * 1024,
        fsync: bool = True,
    ) -> None:
        if isinstance(max_file_size_bytes, bool) or not isinstance(
            max_file_size_bytes,
            int,
        ):
            raise TypeError(
                "max_file_size_bytes must be an integer"
            )

        if max_file_size_bytes < 1024:
            raise ValueError(
                "max_file_size_bytes must be at least 1024"
            )

        if not isinstance(fsync, bool):
            raise TypeError("fsync must be a boolean")

        self.path = Path(path).expanduser()
        self.max_file_size_bytes = max_file_size_bytes
        self.fsync = fsync

        self._lock = threading.RLock()
        self._closed = False

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if self.path.exists():
            if not self.path.is_file():
                raise SecurityAuditError(
                    "Audit log path is not a regular file"
                )

            try:
                os.chmod(self.path, 0o600)
            except OSError as exc:
                raise SecurityAuditError(
                    "Unable to secure existing audit log permissions"
                ) from exc

        else:
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )

            os.close(descriptor)

    def record(
        self,
        event: SecurityAuditEvent,
    ) -> None:
        """Append a security event to the audit log."""

        if not isinstance(event, SecurityAuditEvent):
            raise TypeError(
                "event must be a SecurityAuditEvent"
            )

        serialized = _serialize_event(event)
        line = serialized + "\n"
        encoded = line.encode("utf-8")

        with self._lock:
            self._ensure_open()

            try:
                current_size = self.path.stat().st_size

                if current_size + len(encoded) > self.max_file_size_bytes:
                    raise SecurityAuditError(
                        "Security audit log reached its size limit"
                    )

                descriptor = os.open(
                    self.path,
                    os.O_WRONLY | os.O_APPEND,
                )

                try:
                    view = memoryview(encoded)

                    while view:
                        written = os.write(descriptor, view)

                        if written <= 0:
                            raise OSError(
                                "Audit log write made no progress"
                            )

                        view = view[written:]

                    if self.fsync:
                        os.fsync(descriptor)

                finally:
                    os.close(descriptor)

            except SecurityAuditError:
                raise

            except OSError as exc:
                logger.exception(
                    "Failed to append configuration API security audit event"
                )

                raise SecurityAuditError(
                    "Unable to persist security audit event"
                ) from exc

    def record_event(
        self,
        event_type: SecurityAuditEventType,
        **kwargs: Any,
    ) -> SecurityAuditEvent:
        """Create and persist a security event."""

        event = SecurityAuditEvent(
            event_type=event_type,
            **kwargs,
        )

        self.record(event)

        return event

    def read_events(
        self,
        *,
        limit: int = 100,
        event_type: SecurityAuditEventType | None = None,
        principal_id: str | None = None,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Read recent matching audit events.

        Results are returned in chronological order.
        """

        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000")

        if (
            event_type is not None
            and not isinstance(event_type, SecurityAuditEventType)
        ):
            raise TypeError(
                "event_type must be a SecurityAuditEventType or None"
            )

        if since is not None:
            if not isinstance(since, datetime):
                raise TypeError("since must be a datetime")

            if since.tzinfo is None or since.utcoffset() is None:
                raise ValueError("since must be timezone-aware")

            since = since.astimezone(timezone.utc)

        with self._lock:
            self._ensure_open()

            try:
                with self.path.open(
                    "r",
                    encoding="utf-8",
                ) as handle:
                    matching: list[dict[str, Any]] = []

                    for line_number, line in enumerate(handle, start=1):
                        if len(line.encode("utf-8")) > _MAX_EVENT_SIZE:
                            raise SecurityAuditError(
                                f"Audit record at line {line_number} "
                                "exceeds maximum size"
                            )

                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise SecurityAuditError(
                                f"Malformed audit record at line {line_number}"
                            ) from exc

                        if not isinstance(payload, dict):
                            raise SecurityAuditError(
                                f"Invalid audit record at line {line_number}"
                            )

                        if (
                            event_type is not None
                            and payload.get("event_type")
                            != event_type.value
                        ):
                            continue

                        if (
                            principal_id is not None
                            and payload.get("principal_id")
                            != principal_id
                        ):
                            continue

                        if since is not None:
                            try:
                                occurred_at = datetime.fromisoformat(
                                    payload["occurred_at"]
                                )
                            except (
                                KeyError,
                                TypeError,
                                ValueError,
                            ) as exc:
                                raise SecurityAuditError(
                                    f"Invalid timestamp at line {line_number}"
                                ) from exc

                            if (
                                occurred_at.tzinfo is None
                                or occurred_at.utcoffset() is None
                            ):
                                raise SecurityAuditError(
                                    f"Naive timestamp at line {line_number}"
                                )

                            if occurred_at < since:
                                continue

                        matching.append(payload)

                        if len(matching) > limit:
                            matching.pop(0)

                    return matching

            except SecurityAuditError:
                raise

            except OSError as exc:
                raise SecurityAuditError(
                    "Unable to read security audit log"
                ) from exc

    def prune_before(
        self,
        cutoff: datetime,
    ) -> int:
        """Remove events older than cutoff using atomic replacement."""

        if not isinstance(cutoff, datetime):
            raise TypeError("cutoff must be a datetime")

        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("cutoff must be timezone-aware")

        cutoff = cutoff.astimezone(timezone.utc)

        with self._lock:
            self._ensure_open()

            retained: list[str] = []
            removed = 0

            try:
                with self.path.open(
                    "r",
                    encoding="utf-8",
                ) as handle:
                    for line_number, line in enumerate(handle, start=1):
                        try:
                            payload = json.loads(line)
                            occurred_at = datetime.fromisoformat(
                                payload["occurred_at"]
                            )

                            if (
                                occurred_at.tzinfo is None
                                or occurred_at.utcoffset() is None
                            ):
                                raise ValueError(
                                    "Timestamp must be timezone-aware"
                                )

                            if (
                                occurred_at.astimezone(timezone.utc)
                                < cutoff
                            ):
                                removed += 1
                            else:
                                retained.append(line)

                        except (
                            json.JSONDecodeError,
                            KeyError,
                            TypeError,
                            ValueError,
                        ) as exc:
                            raise SecurityAuditError(
                                f"Invalid audit record at line {line_number}"
                            ) from exc

                temporary_path = self.path.with_name(
                    f".{self.path.name}.{uuid.uuid4().hex}.tmp"
                )

                try:
                    descriptor = os.open(
                        temporary_path,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                        0o600,
                    )

                    try:
                        for line in retained:
                            encoded = line.encode("utf-8")
                            view = memoryview(encoded)

                            while view:
                                written = os.write(descriptor, view)

                                if written <= 0:
                                    raise OSError(
                                        "Audit replacement write made no progress"
                                    )

                                view = view[written:]

                        if self.fsync:
                            os.fsync(descriptor)

                    finally:
                        os.close(descriptor)

                    os.replace(
                        temporary_path,
                        self.path,
                    )

                    if self.fsync:
                        directory_descriptor = os.open(
                            self.path.parent,
                            os.O_RDONLY,
                        )

                        try:
                            os.fsync(directory_descriptor)
                        finally:
                            os.close(directory_descriptor)

                finally:
                    if temporary_path.exists():
                        temporary_path.unlink()

                return removed

            except SecurityAuditError:
                raise

            except OSError as exc:
                logger.exception(
                    "Failed to prune configuration API security audit log"
                )

                raise SecurityAuditError(
                    "Unable to prune security audit log"
                ) from exc

    def close(self) -> None:
        """Mark the audit logger as closed."""

        with self._lock:
            self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise SecurityAuditError(
                "Security audit logger is closed"
            )


__all__ = [
    "SecurityAuditEventType",
    "SecurityAuditEvent",
    "SecurityAuditError",
    "SecurityAuditLogger",
]
