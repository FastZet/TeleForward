"""
TeleForward classification manager.

Coordinates registered classifiers and aggregates their results for
individual messages and batches of messages.
"""

from __future__ import annotations

import asyncio
import logging
import time

from dataclasses import dataclass
from typing import Sequence

from app.services.classification.base import (
    BaseClassifier,
    ClassificationInput,
    ClassificationLabel,
    ClassificationResult,
    ClassificationStatus,
)
from app.services.classification.registry import ClassifierRegistry


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClassificationSummary:
    """Aggregated classification output for one message."""

    message_id: int
    results: tuple[ClassificationResult, ...]
    labels: tuple[ClassificationLabel, ...]
    primary_label: ClassificationLabel | None
    processing_time_ms: float

    @property
    def successful_count(self) -> int:
        return sum(
            result.status == ClassificationStatus.COMPLETED
            for result in self.results
        )

    @property
    def failed_count(self) -> int:
        return sum(
            result.status == ClassificationStatus.FAILED
            for result in self.results
        )

    @property
    def skipped_count(self) -> int:
        return sum(
            result.status == ClassificationStatus.SKIPPED
            for result in self.results
        )


class ClassificationManager:
    """Runs and aggregates registered message classifiers."""

    def __init__(
        self,
        registry: ClassifierRegistry,
        *,
        max_concurrency: int = 5,
    ) -> None:
        if not isinstance(registry, ClassifierRegistry):
            raise TypeError(
                "registry must be a ClassifierRegistry instance."
            )

        if (
            isinstance(max_concurrency, bool)
            or not isinstance(max_concurrency, int)
            or max_concurrency < 1
        ):
            raise ValueError(
                "max_concurrency must be a positive integer."
            )

        self.registry = registry
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def _run_classifier(
        self,
        classifier: BaseClassifier,
        classification_input: ClassificationInput,
    ) -> ClassificationResult:
        """Execute one classifier and normalise unexpected failures."""
        started_at = time.perf_counter()

        try:
            async with self._semaphore:
                result = await classifier.classify(
                    classification_input
                )

            if not isinstance(result, ClassificationResult):
                raise TypeError(
                    f"Classifier {classifier.name!r} returned "
                    "an invalid result type."
                )

            return result

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Classifier execution failed",
                extra={
                    "classifier": classifier.name,
                    "message_id": classification_input.message_id,
                },
            )

            return ClassificationResult(
                classifier=classifier.name,
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

    async def classify(
        self,
        classification_input: ClassificationInput,
        *,
        classifier_names: Sequence[str] | None = None,
    ) -> ClassificationSummary:
        """Run enabled classifiers against one message."""
        if not isinstance(
            classification_input,
            ClassificationInput,
        ):
            raise TypeError(
                "classification_input must be a ClassificationInput."
            )

        started_at = time.perf_counter()

        if classifier_names is None:
            classifiers = self.registry.get_all(enabled_only=True)
        else:
            requested_names = tuple(classifier_names)

            if len(requested_names) != len(set(
                name.strip().lower()
                for name in requested_names
            )):
                raise ValueError(
                    "classifier_names cannot contain duplicates."
                )

            classifiers = tuple(
                self.registry.get(name)
                for name in requested_names
            )

            classifiers = tuple(
                classifier
                for classifier in classifiers
                if classifier.enabled
            )

        tasks = [
            self._run_classifier(
                classifier,
                classification_input,
            )
            for classifier in classifiers
        ]

        results = tuple(
            await asyncio.gather(*tasks)
        )

        labels = self._aggregate_labels(results)

        primary_label = (
            max(labels, key=lambda label: label.confidence)
            if labels
            else None
        )

        elapsed_ms = (
            time.perf_counter() - started_at
        ) * 1000

        return ClassificationSummary(
            message_id=classification_input.message_id,
            results=results,
            labels=labels,
            primary_label=primary_label,
            processing_time_ms=elapsed_ms,
        )

    async def classify_many(
        self,
        inputs: Sequence[ClassificationInput],
        *,
        classifier_names: Sequence[str] | None = None,
    ) -> tuple[ClassificationSummary, ...]:
        """Classify multiple messages with bounded concurrency."""
        if len(inputs) == 0:
            return ()

        if len(inputs) > 1000:
            raise ValueError(
                "A classification batch cannot exceed 1000 messages."
            )

        if not all(
            isinstance(item, ClassificationInput)
            for item in inputs
        ):
            raise TypeError(
                "Every batch item must be a ClassificationInput."
            )

        tasks = [
            self.classify(
                item,
                classifier_names=classifier_names,
            )
            for item in inputs
        ]

        return tuple(await asyncio.gather(*tasks))

    @staticmethod
    def _aggregate_labels(
        results: Sequence[ClassificationResult],
    ) -> tuple[ClassificationLabel, ...]:
        """
        Merge labels by category and name.

        When multiple classifiers produce the same label, retain the
        occurrence with the highest confidence.
        """
        aggregated: dict[
            tuple[str, str],
            ClassificationLabel,
        ] = {}

        for result in results:
            if result.status != ClassificationStatus.COMPLETED:
                continue

            for label in result.labels:
                key = (
                    (label.category or "").strip().lower(),
                    label.name.strip().lower(),
                )

                existing = aggregated.get(key)

                if (
                    existing is None
                    or label.confidence > existing.confidence
                ):
                    aggregated[key] = label

        return tuple(
            sorted(
                aggregated.values(),
                key=lambda label: (
                    -label.confidence,
                    (label.category or "").lower(),
                    label.name.lower(),
                ),
            )
        )
