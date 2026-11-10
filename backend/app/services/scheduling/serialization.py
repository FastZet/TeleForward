"""JSON serialization utilities for TeleForward scheduling."""

from __future__ import annotations

import json
import math
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID


class SchedulingSerializationError(ValueError):
    """Raised when a scheduling value cannot be serialized."""


def to_json_compatible(
    value: Any,
    *,
    max_depth: int = 32,
) -> Any:
    """Convert supported Python values into JSON-compatible values.

    Supported types:
    - Dataclasses
    - Enums
    - Date and datetime objects
    - Timedelta objects
    - UUID objects
    - Paths
    - Mappings
    - Lists, tuples, and sets
    - Primitive JSON values

    Datetime values are converted to ISO 8601 strings.
    Timedelta values are converted to seconds.
    """

    if (
        isinstance(max_depth, bool)
        or not isinstance(max_depth, int)
        or max_depth < 1
    ):
        raise ValueError("max_depth must be a positive integer")

    def convert(
        item: Any,
        *,
        depth: int,
        active_ids: set[int],
    ) -> Any:
        if depth > max_depth:
            raise SchedulingSerializationError(
                f"Maximum serialization depth of {max_depth} exceeded"
            )

        if item is None or isinstance(item, (str, bool, int)):
            return item

        if isinstance(item, float):
            if not math.isfinite(item):
                raise SchedulingSerializationError(
                    "NaN and infinity are not valid JSON numbers"
                )
            return item

        if isinstance(item, Enum):
            return convert(
                item.value,
                depth=depth + 1,
                active_ids=active_ids,
            )

        if isinstance(item, datetime):
            return item.isoformat()

        if isinstance(item, date):
            return item.isoformat()

        if isinstance(item, timedelta):
            return item.total_seconds()

        if isinstance(item, UUID):
            return str(item)

        if isinstance(item, Path):
            return str(item)

        if is_dataclass(item) and not isinstance(item, type):
            object_id = id(item)

            if object_id in active_ids:
                raise SchedulingSerializationError(
                    "Circular reference detected in dataclass"
                )

            active_ids.add(object_id)

            try:
                return {
                    field_info.name: convert(
                        getattr(item, field_info.name),
                        depth=depth + 1,
                        active_ids=active_ids,
                    )
                    for field_info in fields(item)
                }
            finally:
                active_ids.remove(object_id)

        if isinstance(item, Mapping):
            object_id = id(item)

            if object_id in active_ids:
                raise SchedulingSerializationError(
                    "Circular reference detected in mapping"
                )

            active_ids.add(object_id)

            try:
                result: dict[str, Any] = {}

                for key, nested_value in item.items():
                    if not isinstance(key, str):
                        raise SchedulingSerializationError(
                            "JSON object keys must be strings"
                        )

                    result[key] = convert(
                        nested_value,
                        depth=depth + 1,
                        active_ids=active_ids,
                    )

                return result
            finally:
                active_ids.remove(object_id)

        if isinstance(item, (list, tuple, set, frozenset)):
            object_id = id(item)

            if object_id in active_ids:
                raise SchedulingSerializationError(
                    "Circular reference detected in collection"
                )

            active_ids.add(object_id)

            try:
                converted = [
                    convert(
                        nested_value,
                        depth=depth + 1,
                        active_ids=active_ids,
                    )
                    for nested_value in item
                ]

                if isinstance(item, (set, frozenset)):
                    # Sets have no guaranteed JSON ordering.
                    converted.sort(key=lambda value: json.dumps(
                        value,
                        sort_keys=True,
                        separators=(",", ":"),
                    ))

                return converted
            finally:
                active_ids.remove(object_id)

        raise SchedulingSerializationError(
            f"Unsupported serialization type: {type(item).__name__}"
        )

    return convert(
        value,
        depth=0,
        active_ids=set(),
    )


def serialize(
    value: Any,
    *,
    indent: int | None = None,
    sort_keys: bool = False,
    max_depth: int = 32,
) -> str:
    """Serialize a scheduling value into a JSON string."""

    try:
        converted = to_json_compatible(
            value,
            max_depth=max_depth,
        )

        return json.dumps(
            converted,
            ensure_ascii=False,
            allow_nan=False,
            indent=indent,
            sort_keys=sort_keys,
            separators=None if indent is not None else (",", ":"),
        )

    except SchedulingSerializationError:
        raise

    except (TypeError, ValueError, OverflowError) as exc:
        raise SchedulingSerializationError(
            f"Could not serialize scheduling value: {exc}"
        ) from exc


def deserialize(
    payload: str | bytes | bytearray,
) -> Any:
    """Decode a JSON payload.

    This function does not reconstruct arbitrary Python objects.
    Datetimes, enums, UUIDs, and other encoded values remain strings
    until an appropriate domain-specific parser handles them.
    """

    if not isinstance(payload, (str, bytes, bytearray)):
        raise TypeError("payload must be a string or bytes")

    try:
        return json.loads(payload)

    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SchedulingSerializationError(
            f"Invalid scheduling JSON payload: {exc}"
        ) from exc


def serialize_datetime(value: datetime) -> str:
    """Serialize a timezone-aware datetime as ISO 8601."""

    if not isinstance(value, datetime):
        raise TypeError("value must be a datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "Datetime must be timezone-aware"
        )

    return value.isoformat()


def deserialize_datetime(value: str) -> datetime:
    """Parse an ISO 8601 datetime and require timezone information."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("value must be a non-empty ISO 8601 string")

    try:
        result = datetime.fromisoformat(value)

    except ValueError as exc:
        raise SchedulingSerializationError(
            f"Invalid ISO 8601 datetime: {value}"
        ) from exc

    if result.tzinfo is None or result.utcoffset() is None:
        raise SchedulingSerializationError(
            "Serialized datetime must include timezone information"
        )

    return result


def serialize_job_definition(definition: Any) -> str:
    """Serialize a scheduled job definition."""

    if not is_dataclass(definition) or isinstance(definition, type):
        raise TypeError(
            "definition must be a dataclass instance"
        )

    return serialize(definition, sort_keys=True)


def serialize_scheduling_event(event: Any) -> str:
    """Serialize a scheduling lifecycle event."""

    from app.services.scheduling.events import SchedulingEvent

    if not isinstance(event, SchedulingEvent):
        raise TypeError(
            "event must be a SchedulingEvent"
        )

    return serialize(event, sort_keys=True)


def serialize_task_result(result: Any) -> str:
    """Serialize a scheduled task result."""

    from app.services.scheduling.base import ScheduledTaskResult

    if not isinstance(result, ScheduledTaskResult):
        raise TypeError(
            "result must be a ScheduledTaskResult"
        )

    return serialize(result, sort_keys=True)


def normalize_utc(value: datetime) -> datetime:
    """Convert a timezone-aware datetime to UTC."""

    if not isinstance(value, datetime):
        raise TypeError("value must be a datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "Datetime must be timezone-aware"
        )

    return value.astimezone(timezone.utc)
