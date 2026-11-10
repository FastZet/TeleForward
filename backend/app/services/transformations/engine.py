"""
TeleForward transformation execution engine.

Executes registered message transformations in their configured
order and produces a consolidated transformation result.
"""

from __future__ import annotations

import asyncio
import logging
import time

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.services.transformations.base import (
    BaseTransformation,
    TransformationInput,
    TransformationOutput,
    TransformationStatus,
)
from app.services.transformations.registry import (
    TransformationRegistry,
)


logger = logging.getLogger(__name__)

MAX_PIPELINE_TRANSFORMATIONS = 100
MAX_PIPELINE_METADATA_FIELDS = 200


@dataclass(frozen=True, slots=True)
class TransformationSummary:
    """Consolidated result of a transformation pipeline."""

    message_id: int
    status: TransformationStatus
    original_text: str
    transformed_text: str
    original_caption: str
    transformed_caption: str
    results: tuple[TransformationOutput, ...] = ()
    changed: bool = False
    processing_time_ms: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if (
            isinstance(self.message_id, bool)
            or not isinstance(self.message_id, int)
            or self.message_id <= 0
        ):
            raise ValueError("message_id must be positive.")

        if not isinstance(self.status, TransformationStatus):
            raise TypeError(
                "status must be a TransformationStatus."
            )

        if not isinstance(self.results, tuple):
            raise TypeError("results must be a tuple.")

        if len(self.results) > MAX_PIPELINE_TRANSFORMATIONS:
            raise ValueError(
                "Too many transformation results."
            )

        if not isinstance(self.changed, bool):
            raise TypeError("changed must be a boolean.")

        if (
            isinstance(self.processing_time_ms, bool)
            or not isinstance(
                self.processing_time_ms,
                (int, float),
            )
            or self.processing_time_ms < 0
        ):
            raise ValueError(
                "processing_time_ms must be non-negative."
            )

        if self.status == TransformationStatus.FAILED:
            if not self.error:
                raise ValueError(
                    "Failed pipeline results require an error."
                )
        elif self.error is not None:
            raise ValueError(
                "Only failed pipeline results may contain an error."
            )

        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be a dictionary.")

        if len(self.metadata) > MAX_PIPELINE_METADATA_FIELDS:
            raise ValueError("Too many pipeline metadata fields.")

        if (
            not isinstance(self.created_at, datetime)
            or self.created_at.tzinfo is None
            or self.created_at.utcoffset() is None
        ):
            raise ValueError(
                "created_at must be timezone-aware."
            )


class TransformationEngine:
    """
    Executes a sequence of registered transformations.

    By default, a failed transformation stops the pipeline.
    """

    def __init__(
        self,
        registry: TransformationRegistry,
        *,
        max_transformations: int = 50,
        continue_on_error: bool = False,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not isinstance(registry, TransformationRegistry):
            raise TypeError(
                "registry must be a TransformationRegistry."
            )

        if (
            isinstance(max_transformations, bool)
            or not isinstance(max_transformations, int)
            or not 1 <= max_transformations
            <= MAX_PIPELINE_TRANSFORMATIONS
        ):
            raise ValueError(
                "max_transformations must be between 1 and "
                f"{MAX_PIPELINE_TRANSFORMATIONS}."
            )

        if not isinstance(continue_on_error, bool):
            raise TypeError(
                "continue_on_error must be a boolean."
            )

        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise ValueError(
                "timeout_seconds must be positive."
            )

        self.registry = registry
        self.max_transformations = max_transformations
        self.continue_on_error = continue_on_error
        self.timeout_seconds = float(timeout_seconds)

    async def execute(
        self,
        transformation_input: TransformationInput,
        *,
        transformation_names: list[str] | tuple[str, ...] | None = None,
    ) -> TransformationSummary:
        """Execute the configured transformation pipeline."""
        started_at = time.perf_counter()

        original_text = transformation_input.text
        original_caption = transformation_input.caption

        current_text = original_text
        current_caption = original_caption

        results: list[TransformationOutput] = []

        if transformation_names is None:
            transformations = self.registry.get_all(
                enabled_only=True
            )
        else:
            if not isinstance(
                transformation_names,
                (list, tuple),
            ):
                raise TypeError(
                    "transformation_names must be a list or tuple."
                )

            if len(transformation_names) > self.max_transformations:
                raise ValueError(
                    "Requested transformation count exceeds the limit."
                )

            if len(set(transformation_names)) != len(
                transformation_names
            ):
                raise ValueError(
                    "Duplicate transformation names are not allowed."
                )

            transformations = [
                self.registry.get(name)
                for name in transformation_names
            ]

            transformations = [
                transformation
                for transformation in transformations
                if transformation.enabled
            ]

        if len(transformations) > self.max_transformations:
            raise ValueError(
                "Registered transformation count exceeds the limit."
            )

        try:
            for transformation in transformations:
                current_input = TransformationInput(
                    message_id=transformation_input.message_id,
                    account_id=transformation_input.account_id,
                    chat_id=transformation_input.chat_id,
                    text=current_text,
                    caption=current_caption,
                    media_type=transformation_input.media_type,
                    sender_id=transformation_input.sender_id,
                    metadata=transformation_input.metadata,
                )

                try:
                    result = await asyncio.wait_for(
                        transformation.transform(current_input),
                        timeout=self.timeout_seconds,
                    )

                    if not isinstance(result, TransformationOutput):
                        raise TypeError(
                            f"Transformation '{transformation.name}' "
                            "did not return TransformationOutput."
                        )

                    if result.transformation != transformation.name:
                        raise ValueError(
                            f"Transformation '{transformation.name}' "
                            "returned a result with an inconsistent name."
                        )

                except asyncio.CancelledError:
                    raise

                except Exception as exc:
                    logger.exception(
                        "Transformation execution failed",
                        extra={
                            "message_id": transformation_input.message_id,
                            "transformation": transformation.name,
                        },
                    )

                    failure = TransformationOutput(
                        transformation=transformation.name,
                        status=TransformationStatus.FAILED,
                        text=current_text,
                        caption=current_caption,
                        changed=False,
                        processing_time_ms=0.0,
                        error=str(exc)[:2000],
                        metadata={
                            "error_type": type(exc).__name__,
                        },
                    )

                    results.append(failure)

                    if not self.continue_on_error:
                        elapsed_ms = (
                            time.perf_counter() - started_at
                        ) * 1000

                        return TransformationSummary(
                            message_id=transformation_input.message_id,
                            status=TransformationStatus.FAILED,
                            original_text=original_text,
                            transformed_text=current_text,
                            original_caption=original_caption,
                            transformed_caption=current_caption,
                            results=tuple(results),
                            changed=(
                                current_text != original_text
                                or current_caption != original_caption
                            ),
                            processing_time_ms=elapsed_ms,
                            error=(
                                f"Transformation '{transformation.name}' "
                                "failed."
                            ),
                        )

                    continue

                results.append(result)

                if result.status == TransformationStatus.FAILED:
                    if not self.continue_on_error:
                        elapsed_ms = (
                            time.perf_counter() - started_at
                        ) * 1000

                        return TransformationSummary(
                            message_id=transformation_input.message_id,
                            status=TransformationStatus.FAILED,
                            original_text=original_text,
                            transformed_text=current_text,
                            original_caption=original_caption,
                            transformed_caption=current_caption,
                            results=tuple(results),
                            changed=(
                                current_text != original_text
                                or current_caption != original_caption
                            ),
                            processing_time_ms=elapsed_ms,
                            error=result.error,
                        )

                    continue

                if result.status == TransformationStatus.COMPLETED:
                    current_text = result.text
                    current_caption = result.caption

            failed = any(
                result.status == TransformationStatus.FAILED
                for result in results
            )

            skipped = (
                bool(results)
                and all(
                    result.status == TransformationStatus.SKIPPED
                    for result in results
                )
            )

            status = (
                TransformationStatus.FAILED
                if failed
                else (
                    TransformationStatus.SKIPPED
                    if skipped
                    else TransformationStatus.COMPLETED
                )
            )

            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            return TransformationSummary(
                message_id=transformation_input.message_id,
                status=status,
                original_text=original_text,
                transformed_text=current_text,
                original_caption=original_caption,
                transformed_caption=current_caption,
                results=tuple(results),
                changed=(
                    current_text != original_text
                    or current_caption != original_caption
                ),
                processing_time_ms=elapsed_ms,
                metadata={
                    "transformation_count": len(results),
                    "completed_count": sum(
                        result.status == TransformationStatus.COMPLETED
                        for result in results
                    ),
                    "skipped_count": sum(
                        result.status == TransformationStatus.SKIPPED
                        for result in results
                    ),
                    "failed_count": sum(
                        result.status == TransformationStatus.FAILED
                        for result in results
                    ),
                },
            )

        except asyncio.CancelledError:
            logger.warning(
                "Transformation pipeline cancelled",
                extra={
                    "message_id": transformation_input.message_id,
                },
            )
            raise

    async def execute_many(
        self,
        inputs: list[TransformationInput],
        *,
        concurrency: int = 5,
    ) -> list[TransformationSummary]:
        """Execute transformations for multiple messages."""
        if not isinstance(inputs, list):
            raise TypeError("inputs must be a list.")

        if any(
            not isinstance(item, TransformationInput)
            for item in inputs
        ):
            raise TypeError(
                "Every input must be a TransformationInput."
            )

        if (
            isinstance(concurrency, bool)
            or not isinstance(concurrency, int)
            or concurrency < 1
        ):
            raise ValueError(
                "concurrency must be a positive integer."
            )

        semaphore = asyncio.Semaphore(concurrency)

        async def run_one(
            item: TransformationInput,
        ) -> TransformationSummary:
            async with semaphore:
                return await self.execute(item)

        tasks = [
            asyncio.create_task(run_one(item))
            for item in inputs
        ]

        return list(
            await asyncio.gather(*tasks)
        )
