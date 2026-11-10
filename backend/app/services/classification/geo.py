"""
TeleForward geographic metadata classifier.

Classifies geographic information explicitly supplied through
Telegram message metadata.

This module does not perform geocoding, reverse geocoding, external
location lookups or address inference.
"""

from __future__ import annotations

import logging
import math
import time

from collections.abc import Mapping
from typing import Any

from app.services.classification.base import (
    BaseClassifier,
    ClassificationInput,
    ClassificationLabel,
    ClassificationResult,
    ClassificationStatus,
)


logger = logging.getLogger(__name__)

MAX_COORDINATE_PRECISION = 8

LOCATION_METADATA_KEYS = (
    "location",
    "geo",
    "coordinates",
    "venue",
    "live_location",
    "geo_point",
)

LATITUDE_KEYS = (
    "latitude",
    "lat",
)

LONGITUDE_KEYS = (
    "longitude",
    "lon",
    "lng",
)

LOCATION_TYPES = frozenset({
    "location",
    "live_location",
    "venue",
    "geo",
    "geo_point",
})


class GeoClassifier(BaseClassifier):
    """Classify geographic information in Telegram messages."""

    name = "geo"
    version = "1.0.0"

    def __init__(
        self,
        *,
        include_coordinates: bool = True,
        include_venue: bool = True,
        include_live_location: bool = True,
        enabled: bool = True,
        minimum_confidence: float = 0.0,
    ) -> None:
        super().__init__(
            enabled=enabled,
            minimum_confidence=minimum_confidence,
        )

        for name, value in (
            ("include_coordinates", include_coordinates),
            ("include_venue", include_venue),
            ("include_live_location", include_live_location),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a boolean.")

        self.include_coordinates = include_coordinates
        self.include_venue = include_venue
        self.include_live_location = include_live_location

    @staticmethod
    def _normalise_coordinate(
        value: Any,
        *,
        minimum: float,
        maximum: float,
    ) -> float | None:
        """Validate and normalise a geographic coordinate."""
        if isinstance(value, bool):
            return None

        if not isinstance(value, (int, float)):
            return None

        coordinate = float(value)

        if not math.isfinite(coordinate):
            return None

        if not minimum <= coordinate <= maximum:
            return None

        return round(
            coordinate,
            MAX_COORDINATE_PRECISION,
        )

    @classmethod
    def _extract_coordinates(
        cls,
        value: Any,
    ) -> tuple[float, float] | None:
        """Extract latitude and longitude from supported structures."""
        if isinstance(value, Mapping):
            latitude = None
            longitude = None

            for key in LATITUDE_KEYS:
                if key in value:
                    latitude = value[key]
                    break

            for key in LONGITUDE_KEYS:
                if key in value:
                    longitude = value[key]
                    break

            if latitude is None or longitude is None:
                nested = value.get("coordinates")

                if nested is not None:
                    return cls._extract_coordinates(nested)

                return None

        elif (
            isinstance(value, (list, tuple))
            and len(value) == 2
        ):
            # Coordinate arrays use the conventional latitude,
            # longitude order in this classifier.
            latitude, longitude = value

        else:
            return None

        normalised_latitude = cls._normalise_coordinate(
            latitude,
            minimum=-90.0,
            maximum=90.0,
        )

        normalised_longitude = cls._normalise_coordinate(
            longitude,
            minimum=-180.0,
            maximum=180.0,
        )

        if (
            normalised_latitude is None
            or normalised_longitude is None
        ):
            return None

        return normalised_latitude, normalised_longitude

    @staticmethod
    def _extract_location_type(
        metadata: Mapping[str, Any],
    ) -> str | None:
        """Determine the location type from metadata."""
        explicit_type = metadata.get("location_type")

        if isinstance(explicit_type, str):
            normalised = explicit_type.strip().casefold()

            if normalised in LOCATION_TYPES:
                return normalised

        for key in LOCATION_METADATA_KEYS:
            if key in metadata and metadata[key] is not None:
                return key

        return None

    @staticmethod
    def _extract_venue(
        metadata: Mapping[str, Any],
    ) -> dict[str, str]:
        """Extract venue name and address without inferring values."""
        venue = metadata.get("venue")

        if not isinstance(venue, Mapping):
            return {}

        result: dict[str, str] = {}

        for field in ("title", "name", "address"):
            value = venue.get(field)

            if isinstance(value, str) and value.strip():
                result[field] = value.strip()[:512]

        return result

    def _build_labels(
        self,
        *,
        coordinates: tuple[float, float] | None,
        location_type: str | None,
        venue: Mapping[str, str],
        live_location: bool,
    ) -> tuple[ClassificationLabel, ...]:
        """Generate geographic classification labels."""
        labels: list[ClassificationLabel] = []

        if coordinates is not None and self.include_coordinates:
            labels.append(
                ClassificationLabel(
                    name="coordinates_available",
                    category="geographic_information",
                    confidence=1.0,
                )
            )

        if (
            location_type == "venue"
            and self.include_venue
        ):
            labels.append(
                ClassificationLabel(
                    name="venue",
                    category="geographic_type",
                    confidence=1.0,
                )
            )

        elif (
            location_type is not None
            and location_type != "venue"
        ):
            labels.append(
                ClassificationLabel(
                    name="location",
                    category="geographic_type",
                    confidence=1.0,
                )
            )

        if (
            live_location
            and self.include_live_location
        ):
            labels.append(
                ClassificationLabel(
                    name="live_location",
                    category="geographic_type",
                    confidence=1.0,
                )
            )

        if venue:
            labels.append(
                ClassificationLabel(
                    name="venue_details_available",
                    category="geographic_information",
                    confidence=1.0,
                )
            )

        return tuple(labels)

    async def classify(
        self,
        classification_input: ClassificationInput,
    ) -> ClassificationResult:
        """Classify geographic message metadata."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                classifier=self.name,
                reason="Geographic classifier is disabled.",
            )

        try:
            metadata = classification_input.metadata

            location_type = self._extract_location_type(
                metadata
            )

            coordinates = None

            # Prefer explicitly supplied top-level coordinates.
            coordinates = self._extract_coordinates(metadata)

            if coordinates is None:
                for key in LOCATION_METADATA_KEYS:
                    if key not in metadata:
                        continue

                    coordinates = self._extract_coordinates(
                        metadata[key]
                    )

                    if coordinates is not None:
                        break

            venue = self._extract_venue(metadata)

            live_location = (
                location_type == "live_location"
                or metadata.get("live_location") is True
            )

            labels = self.filter_by_confidence(
                self._build_labels(
                    coordinates=coordinates,
                    location_type=location_type,
                    venue=venue,
                    live_location=live_location,
                )
            )

            primary_label = labels[0] if labels else None

            result_metadata: dict[str, Any] = {
                "message_id": classification_input.message_id,
                "account_id": classification_input.account_id,
                "chat_id": classification_input.chat_id,
                "has_location": (
                    coordinates is not None
                    or bool(venue)
                    or location_type is not None
                ),
                "location_type": location_type,
                "has_coordinates": coordinates is not None,
                "has_venue_details": bool(venue),
                "is_live_location": live_location,
            }

            if coordinates is not None:
                result_metadata["coordinates"] = {
                    "latitude": coordinates[0],
                    "longitude": coordinates[1],
                }

            if venue:
                result_metadata["venue"] = venue

            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            return ClassificationResult(
                classifier=self.name,
                status=ClassificationStatus.COMPLETED,
                labels=labels,
                primary_label=primary_label,
                confidence=(
                    primary_label.confidence
                    if primary_label
                    else 0.0
                ),
                processing_time_ms=elapsed_ms,
                metadata=result_metadata,
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Geographic classification failed",
                extra={
                    "message_id": classification_input.message_id,
                    "classifier": self.name,
                },
            )

            return ClassificationResult(
                classifier=self.name,
                status=ClassificationStatus.FAILED,
                labels=(),
                primary_label=None,
                confidence=0.0,
                processing_time_ms=elapsed_ms,
                error=str(exc)[:2000],
                metadata={
                    "error_type": type(exc).__name__,
                },
            )
