
"""Tests for the scheduling security audit logger."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.services.scheduling.configuration_api_security_audit import (
    SecurityAuditError,
    SecurityAuditEvent,
    SecurityAuditEventType,
    SecurityAuditLogger,
)


UTC = timezone.utc


def make_event(
    *,
    event_type: SecurityAuditEventType = (
        SecurityAuditEventType.AUTHENTICATION_SUCCESS
    ),
    occurred_at: datetime | None = None,
    event_id: str = "event-1",
    principal_id: str | None = "admin-1",
    success: bool = True,
    metadata: dict[str, Any] | None = None,
) -> SecurityAuditEvent:
    """Build a valid event for use in tests."""
    return SecurityAuditEvent(
        event_type=event_type,
        occurred_at=occurred_at or datetime.now(UTC),
        event_id=event_id,
        principal_id=principal_id,
        success=success,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Event validation
# ---------------------------------------------------------------------------


def test_event_accepts_valid_values() -> None:
    event = make_event(
        event_id="audit:event-01",
        metadata={"operation": "login"},
    )

    assert event.event_id == "audit:event-01"
    assert event.event_type is SecurityAuditEventType.AUTHENTICATION_SUCCESS
    assert event.success is True
    assert event.metadata["operation"] == "login"


@pytest.mark.parametrize(
    "event_id",
    [
        "",
        " ",
        "contains spaces",
        "invalid/slash",
        "x" * 129,
    ],
)
def test_event_rejects_invalid_event_ids(event_id: str) -> None:
    with pytest.raises(ValueError):
        make_event(event_id=event_id)


def test_event_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError):
        make_event(occurred_at=datetime(2026, 11, 13, 10, 0, 0))


def test_event_rejects_non_datetime_timestamp() -> None:
    with pytest.raises((TypeError, ValueError)):
        SecurityAuditEvent(
            event_type=SecurityAuditEventType.REQUEST_REJECTED,
            occurred_at="2026-11-13T10:00:00Z",  # type: ignore[arg-type]
        )


def test_event_rejects_invalid_event_type() -> None:
    with pytest.raises((TypeError, ValueError)):
        SecurityAuditEvent(
            event_type="not-an-event-type",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("success", [1, 0, "true", None])
def test_event_rejects_non_boolean_success(success: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        SecurityAuditEvent(
            event_type=SecurityAuditEventType.REQUEST_REJECTED,
            success=success,
        )


def test_event_requires_mapping_metadata() -> None:
    with pytest.raises((TypeError, ValueError)):
        SecurityAuditEvent(
            event_type=SecurityAuditEventType.REQUEST_REJECTED,
            metadata=["not", "a", "mapping"],  # type: ignore[arg-type]
        )


def test_event_copies_top_level_metadata_mapping() -> None:
    metadata = {"operation": "login"}
    event = make_event(metadata=metadata)

    metadata["operation"] = "changed"

    assert event.metadata["operation"] == "login"


# ---------------------------------------------------------------------------
# Logger creation and basic persistence
# ---------------------------------------------------------------------------


def test_logger_creates_parent_directory_and_file(tmp_path: Path) -> None:
    log_path = tmp_path / "nested" / "logs" / "security.jsonl"

    logger = SecurityAuditLogger(log_path)
    try:
        logger.record(make_event())
    finally:
        logger.close()

    assert log_path.is_file()
    assert log_path.parent.is_dir()
    assert len(log_path.read_text(encoding="utf-8").splitlines()) == 1


def test_record_and_read_event(tmp_path: Path) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")
    event = make_event(
        event_id="login-001",
        metadata={"operation": "login"},
    )

    try:
        logger.record(event)
        records = logger.read_events()
    finally:
        logger.close()

    assert len(records) == 1
    assert records[0]["event_id"] == "login-001"
    assert records[0]["event_type"] == "authentication_success"
    assert records[0]["principal_id"] == "admin-1"
    assert records[0]["success"] is True
    assert records[0]["metadata"]["operation"] == "login"


def test_record_event_creates_and_returns_event(tmp_path: Path) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")

    try:
        event = logger.record_event(
            SecurityAuditEventType.AUTHORIZATION_FAILURE,
            principal_id="operator-1",
            success=False,
            reason="permission_denied",
            metadata={"permission": "delete_configuration"},
        )
        records = logger.read_events()
    finally:
        logger.close()

    assert isinstance(event, SecurityAuditEvent)
    assert event.event_type is SecurityAuditEventType.AUTHORIZATION_FAILURE
    assert event.success is False
    assert records[-1]["event_id"] == event.event_id


def test_records_are_written_as_json_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "security.jsonl"
    logger = SecurityAuditLogger(log_path)

    try:
        logger.record(make_event(event_id="one"))
        logger.record(make_event(event_id="two"))
    finally:
        logger.close()

    lines = log_path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2
    assert json.loads(lines[0])["event_id"] == "one"
    assert json.loads(lines[1])["event_id"] == "two"


# ---------------------------------------------------------------------------
# Metadata sanitisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sensitive_key",
    [
        "password",
        "secret",
        "access_token",
        "authorization",
        "cookie",
        "credential",
        "api_key",
        "api-key",
        "session_string",
        "private_key",
    ],
)
def test_sensitive_metadata_values_are_redacted(
    tmp_path: Path,
    sensitive_key: str,
) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")

    try:
        logger.record(
            make_event(
                metadata={
                    sensitive_key: "must-not-be-persisted",
                    "operation": "login",
                }
            )
        )
        record = logger.read_events()[0]
    finally:
        logger.close()

    assert record["metadata"][sensitive_key] == "[REDACTED]"
    assert record["metadata"]["operation"] == "login"
    assert "must-not-be-persisted" not in (
        tmp_path / "security.jsonl"
    ).read_text(encoding="utf-8")


def test_sensitive_keys_are_redacted_recursively(tmp_path: Path) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")

    try:
        logger.record(
            make_event(
                metadata={
                    "context": {
                        "user": "operator",
                        "nested": {
                            "api_key": "nested-secret",
                        },
                    },
                    "items": [
                        {"token": "list-secret"},
                        {"status": "accepted"},
                    ],
                }
            )
        )
        metadata = logger.read_events()[0]["metadata"]
    finally:
        logger.close()

    assert metadata["context"]["nested"]["api_key"] == "[REDACTED]"
    assert metadata["items"][0]["token"] == "[REDACTED]"
    assert metadata["items"][1]["status"] == "accepted"


def test_datetime_metadata_is_serialized_as_iso_timestamp(
    tmp_path: Path,
) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")
    timestamp = datetime(2026, 11, 13, 10, 30, tzinfo=UTC)

    try:
        logger.record(make_event(metadata={"when": timestamp}))
        metadata = logger.read_events()[0]["metadata"]
    finally:
        logger.close()

    assert metadata["when"] == timestamp.isoformat()


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_metadata_numbers_are_safely_serialized(
    tmp_path: Path,
    number: float,
) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")

    try:
        logger.record(make_event(metadata={"value": number}))
        metadata = logger.read_events()[0]["metadata"]
    finally:
        logger.close()

    assert isinstance(metadata["value"], str)


def test_set_metadata_is_serialized_deterministically(tmp_path: Path) -> None:
    log_path = tmp_path / "security.jsonl"
    logger = SecurityAuditLogger(log_path)

    try:
        logger.record(make_event(metadata={"values": {"z", "a", "m"}}))
        metadata = logger.read_events()[0]["metadata"]
    finally:
        logger.close()

    assert metadata["values"] == ["a", "m", "z"]


def test_unsupported_metadata_object_is_marked_safely(
    tmp_path: Path,
) -> None:
    class Unsupported:
        pass

    logger = SecurityAuditLogger(tmp_path / "security.jsonl")

    try:
        logger.record(make_event(metadata={"value": Unsupported()}))
        metadata = logger.read_events()[0]["metadata"]
    finally:
        logger.close()

    assert isinstance(metadata["value"], str)
    assert "unsupported" in metadata["value"].lower()


def test_deep_metadata_does_not_cause_recursion_failure(
    tmp_path: Path,
) -> None:
    value: Any = "leaf"
    for _ in range(20):
        value = {"nested": value}

    logger = SecurityAuditLogger(tmp_path / "security.jsonl")

    try:
        logger.record(make_event(metadata={"value": value}))
        record = logger.read_events()[0]
    finally:
        logger.close()

    assert record["event_id"] == "event-1"


# ---------------------------------------------------------------------------
# Filtering, ordering, and limits
# ---------------------------------------------------------------------------


def test_read_events_returns_chronological_order(tmp_path: Path) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")
    base = datetime(2026, 11, 13, 10, 0, tzinfo=UTC)

    try:
        logger.record(make_event(event_id="first", occurred_at=base))
        logger.record(
            make_event(
                event_id="second",
                occurred_at=base + timedelta(minutes=1),
            )
        )
        logger.record(
            make_event(
                event_id="third",
                occurred_at=base + timedelta(minutes=2),
            )
        )
        records = logger.read_events()
    finally:
        logger.close()

    assert [record["event_id"] for record in records] == [
        "first",
        "second",
        "third",
    ]


def test_read_events_limit_returns_latest_matching_records(
    tmp_path: Path,
) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")

    try:
        for index in range(5):
            logger.record(make_event(event_id=f"event-{index}"))
        records = logger.read_events(limit=2)
    finally:
        logger.close()

    assert [record["event_id"] for record in records] == [
        "event-3",
        "event-4",
    ]


def test_read_events_filters_by_event_type(tmp_path: Path) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")

    try:
        logger.record(
            make_event(
                event_id="auth",
                event_type=SecurityAuditEventType.AUTHENTICATION_SUCCESS,
            )
        )
        logger.record(
            make_event(
                event_id="rate-limit",
                event_type=SecurityAuditEventType.RATE_LIMIT_REJECTED,
            )
        )
        records = logger.read_events(
            event_type=SecurityAuditEventType.RATE_LIMIT_REJECTED
        )
    finally:
        logger.close()

    assert [record["event_id"] for record in records] == ["rate-limit"]


def test_read_events_filters_by_principal(tmp_path: Path) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")

    try:
        logger.record(make_event(event_id="one", principal_id="admin"))
        logger.record(make_event(event_id="two", principal_id="operator"))
        records = logger.read_events(principal_id="operator")
    finally:
        logger.close()

    assert [record["event_id"] for record in records] == ["two"]


def test_read_events_filters_by_since_timestamp(tmp_path: Path) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")
    start = datetime(2026, 11, 13, 10, 0, tzinfo=UTC)
    cutoff = start + timedelta(minutes=1)

    try:
        logger.record(make_event(event_id="old", occurred_at=start))
        logger.record(
            make_event(
                event_id="new",
                occurred_at=cutoff + timedelta(seconds=1),
            )
        )
        records = logger.read_events(since=cutoff)
    finally:
        logger.close()

    assert [record["event_id"] for record in records] == ["new"]


def test_read_events_rejects_naive_since_timestamp(
    tmp_path: Path,
) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")

    try:
        with pytest.raises(ValueError):
            logger.read_events(since=datetime(2026, 11, 13, 10, 0))
    finally:
        logger.close()


def test_read_events_rejects_invalid_limit(tmp_path: Path) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")

    try:
        with pytest.raises((TypeError, ValueError)):
            logger.read_events(limit=0)
    finally:
        logger.close()


# ---------------------------------------------------------------------------
# Size limits and malformed records
# ---------------------------------------------------------------------------


def test_oversized_event_is_rejected(tmp_path: Path) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")

    try:
        with pytest.raises(SecurityAuditError):
            logger.record(
                make_event(metadata={"large": "x" * (70 * 1024)})
            )
    finally:
        logger.close()


def test_file_size_limit_rejects_additional_record(tmp_path: Path) -> None:
    log_path = tmp_path / "security.jsonl"
    logger = SecurityAuditLogger(
        log_path,
        max_file_size_bytes=300,
        fsync=False,
    )

    try:
        logger.record(make_event(event_id="first"))
        with pytest.raises(SecurityAuditError):
            logger.record(
                make_event(
                    event_id="second",
                    metadata={"payload": "x" * 400},
                )
            )
    finally:
        logger.close()


def test_malformed_json_line_is_rejected_on_read(tmp_path: Path) -> None:
    log_path = tmp_path / "security.jsonl"
    log_path.write_text("{invalid json}\n", encoding="utf-8")
    logger = SecurityAuditLogger(log_path)

    try:
        with pytest.raises(SecurityAuditError):
            logger.read_events()
    finally:
        logger.close()


def test_non_object_json_line_is_rejected_on_read(tmp_path: Path) -> None:
    log_path = tmp_path / "security.jsonl"
    log_path.write_text('["not", "an", "event"]\n', encoding="utf-8")
    logger = SecurityAuditLogger(log_path)

    try:
        with pytest.raises(SecurityAuditError):
            logger.read_events()
    finally:
        logger.close()


# ---------------------------------------------------------------------------
# Pruning and lifecycle
# ---------------------------------------------------------------------------


def test_prune_before_removes_old_records_and_keeps_new_ones(
    tmp_path: Path,
) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")
    cutoff = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)

    try:
        logger.record(
            make_event(
                event_id="old",
                occurred_at=cutoff - timedelta(days=1),
            )
        )
        logger.record(
            make_event(
                event_id="recent",
                occurred_at=cutoff + timedelta(seconds=1),
            )
        )
        removed = logger.prune_before(cutoff)
        remaining = logger.read_events()
    finally:
        logger.close()

    assert removed == 1
    assert [record["event_id"] for record in remaining] == ["recent"]


def test_prune_before_rejects_naive_cutoff(tmp_path: Path) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")

    try:
        with pytest.raises(ValueError):
            logger.prune_before(datetime(2026, 11, 13, 12, 0))
    finally:
        logger.close()


def test_prune_before_handles_empty_log(tmp_path: Path) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")

    try:
        removed = logger.prune_before(datetime.now(UTC))
    finally:
        logger.close()

    assert removed == 0


def test_closed_logger_rejects_operations(tmp_path: Path) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")
    logger.close()

    with pytest.raises(SecurityAuditError):
        logger.record(make_event())

    with pytest.raises(SecurityAuditError):
        logger.read_events()

    with pytest.raises(SecurityAuditError):
        logger.prune_before(datetime.now(UTC))


def test_close_is_idempotent(tmp_path: Path) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")

    logger.close()
    logger.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions required")
def test_audit_file_permissions_are_restricted(tmp_path: Path) -> None:
    log_path = tmp_path / "security.jsonl"
    logger = SecurityAuditLogger(log_path)

    try:
        logger.record(make_event())
    finally:
        logger.close()

    mode = log_path.stat().st_mode & 0o777
    assert mode & 0o077 == 0


# ---------------------------------------------------------------------------
# Concurrent writes
# ---------------------------------------------------------------------------


def test_concurrent_writes_produce_valid_jsonl(tmp_path: Path) -> None:
    log_path = tmp_path / "security.jsonl"
    logger = SecurityAuditLogger(log_path, fsync=False)

    def write_event(index: int) -> None:
        logger.record(make_event(event_id=f"concurrent-{index}"))

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(write_event, range(40)))

        records = logger.read_events(limit=100)
    finally:
        logger.close()

    assert len(records) == 40
    assert len({record["event_id"] for record in records}) == 40

    # Independently verify that every physical line is valid JSON.
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 40
    assert all(isinstance(json.loads(line), dict) for line in lines)
