"""
TeleForward metadata transformation.

Provides controlled metadata updates for Telegram messages and captions.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Mapping
from typing import Any

from app.services.transformations.base import (
    BaseTransformation,
    TransformationInput,
    TransformationOutput,
    TransformationStatus,
)

logger = logging.getLogger(__name__)

MAX_METADATA_FIELDS = 100
MAX_METADATA_KEY_LENGTH = 128
MAX_METADATA_VALUE_LENGTH = 4096
MAX_TEMPLATE_VARIABLES = 50

METADATA_KEY_PATTERN = re.compile(
    r"^[a-zA-Z][a-zA-Z0-9_.-]{0,127}$"
)

TEMPLATE_PATTERN = re.compile(
    r"\{([a-zA-Z][a-zA-Z0-9_.-]{0,127})\}"
)


class MetadataTransformation(BaseTransformation):
    """Transform message metadata without modifying Telegram entities."""

    name = "metadata"
    version = "1.0.0"

    def __init__(
        self,
        *,
        add_fields: Mapping[str, Any] | None = None,
        update_fields: Mapping[str, Any] | None = None,
        remove_fields: set[str] | None = None,
        rename_fields: Mapping[str, str] | None = None,
        templates: Mapping[str, str] | None = None,
        overwrite_existing: bool = True,
        include_message_context: bool = True,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)

        if not isinstance(overwrite_existing, bool):
            raise ValueError("overwrite_existing must be a boolean.")

        if not isinstance(include_message_context, bool):
            raise ValueError(
                "include_message_context must be a boolean."
            )

        self.add_fields = self._validate_fields(
            add_fields or {}
        )
        self.update_fields = self._validate_fields(
            update_fields or {}
        )

        self.remove_fields = self._validate_remove_fields(
            remove_fields or set()
        )

        self.rename_fields = self._validate_rename_fields(
            rename_fields or {}
        )

        self.templates = self._validate_templates(
            templates or {}
        )

        self.overwrite_existing = overwrite_existing
        self.include_message_context = include_message_context

    @staticmethod
    def _validate_key(key: str) -> str:
        if not isinstance(key, str):
            raise TypeError("Metadata keys must be strings.")

        if len(key) > MAX_METADATA_KEY_LENGTH:
            raise ValueError("Metadata key is too long.")

        if not METADATA_KEY_PATTERN.fullmatch(key):
            raise ValueError(
                f"Invalid metadata key: {key!r}"
            )

        return key

    @classmethod
    def _validate_fields(
        cls,
        fields: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(fields, Mapping):
            raise TypeError("Metadata fields must be mappings.")

        if len(fields) > MAX_METADATA_FIELDS:
            raise ValueError(
                f"At most {MAX_METADATA_FIELDS} metadata fields "
                "are allowed."
            )

        result: dict[str, Any] = {}

        for key, value in fields.items():
            validated_key = cls._validate_key(key)

            if isinstance(value, str):
                if len(value) > MAX_METADATA_VALUE_LENGTH:
                    raise ValueError(
                        f"Metadata value for {key!r} is too long."
                    )

            result[validated_key] = value

        return result

    @classmethod
    def _validate_remove_fields(
        cls,
        fields: set[str],
    ) -> frozenset[str]:
        if not isinstance(fields, set):
            raise TypeError("remove_fields must be a set.")

        if len(fields) > MAX_METADATA_FIELDS:
            raise ValueError(
                f"At most {MAX_METADATA_FIELDS} fields "
                "can be removed."
            )

        return frozenset(
            cls._validate_key(key)
            for key in fields
        )

    @classmethod
    def _validate_rename_fields(
        cls,
        fields: Mapping[str, str],
    ) -> dict[str, str]:
        if not isinstance(fields, Mapping):
            raise TypeError("rename_fields must be a mapping.")

        if len(fields) > MAX_METADATA_FIELDS:
            raise ValueError(
                "Too many metadata rename operations."
            )

        result: dict[str, str] = {}

        for source, destination in fields.items():
            source_key = cls._validate_key(source)
            destination_key = cls._validate_key(destination)

            if source_key == destination_key:
                continue

            result[source_key] = destination_key

        destinations = list(result.values())

        if len(destinations) != len(set(destinations)):
            raise ValueError(
                "Multiple metadata fields cannot share "
                "the same destination key."
            )

        return result

    @classmethod
    def _validate_templates(
        cls,
        templates: Mapping[str, str],
    ) -> dict[str, str]:
        if not isinstance(templates, Mapping):
            raise TypeError("templates must be a mapping.")

        if len(templates) > MAX_METADATA_FIELDS:
            raise ValueError("Too many metadata templates.")

        result: dict[str, str] = {}

        for key, template in templates.items():
            validated_key = cls._validate_key(key)

            if not isinstance(template, str):
                raise TypeError(
                    f"Template for {key!r} must be a string."
                )

            if len(template) > MAX_METADATA_VALUE_LENGTH:
                raise ValueError(
                    f"Template for {key!r} is too long."
                )

            variables = TEMPLATE_PATTERN.findall(template)

            if len(variables) > MAX_TEMPLATE_VARIABLES:
                raise ValueError(
                    f"Template for {key!r} contains too many variables."
                )

            result[validated_key] = template

        return result

    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return ""

        if isinstance(value, (str, int, float, bool)):
            return str(value)

        return str(value)

    @staticmethod
    def _build_context(
        transformation_input: TransformationInput,
        metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Build a restricted template context."""
        context: dict[str, Any] = dict(metadata)

        context.update({
            "message_id": transformation_input.message_id,
            "account_id": transformation_input.account_id,
            "chat_id": transformation_input.chat_id,
            "sender_id": transformation_input.sender_id,
            "media_type": transformation_input.media_type,
            "text": transformation_input.text,
            "caption": transformation_input.caption,
        })

        return context

    @classmethod
    def _render_template(
        cls,
        template: str,
        context: Mapping[str, Any],
    ) -> str:
        """Render simple named placeholders without expression evaluation."""

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)

            if key not in context:
                raise ValueError(
                    f"Unknown metadata template variable: {key}"
                )

            return cls._stringify(context[key])

        rendered = TEMPLATE_PATTERN.sub(replace, template)

        if len(rendered) > MAX_METADATA_VALUE_LENGTH:
            raise ValueError(
                "Rendered metadata value exceeds the maximum length."
            )

        return rendered

    def _apply_operations(
        self,
        metadata: dict[str, Any],
        transformation_input: TransformationInput,
    ) -> dict[str, Any]:
        """Apply configured metadata operations in a deterministic order."""

        context = self._build_context(
            transformation_input,
            metadata,
        )

        # Remove selected fields first.
        for key in self.remove_fields:
            metadata.pop(key, None)

        # Rename fields without silently overwriting unrelated values.
        for source, destination in self.rename_fields.items():
            if source not in metadata:
                continue

            if destination in metadata and not self.overwrite_existing:
                raise ValueError(
                    f"Cannot rename {source!r}: "
                    f"{destination!r} already exists."
                )

            value = metadata.pop(source)
            metadata[destination] = value

        # Add fields only when absent, unless overwriting is enabled.
        for key, value in self.add_fields.items():
            if key in metadata and not self.overwrite_existing:
                continue

            metadata[key] = value

        # Update fields.
        for key, value in self.update_fields.items():
            if key in metadata or self.overwrite_existing:
                metadata[key] = value

        # Refresh the context after structural operations.
        if self.include_message_context:
            context = self._build_context(
                transformation_input,
                metadata,
            )
        else:
            context = dict(metadata)

        # Render templates last so they can reference updated fields.
        for key, template in self.templates.items():
            if key in metadata and not self.overwrite_existing:
                continue

            metadata[key] = self._render_template(
                template,
                context,
            )

        if len(metadata) > MAX_METADATA_FIELDS:
            raise ValueError(
                f"Result exceeds {MAX_METADATA_FIELDS} metadata fields."
            )

        for key, value in metadata.items():
            self._validate_key(key)

            if isinstance(value, str):
                if len(value) > MAX_METADATA_VALUE_LENGTH:
                    raise ValueError(
                        f"Metadata value for {key!r} is too long."
                    )

        return metadata

    async def transform(
        self,
        transformation_input: TransformationInput,
    ) -> TransformationOutput:
        """Apply metadata transformations to a message."""

        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                transformation_input,
                reason="Metadata transformation is disabled.",
            )

        try:
            original_metadata = dict(
                transformation_input.metadata or {}
            )

            metadata = dict(original_metadata)

            metadata = self._apply_operations(
                metadata,
                transformation_input,
            )

            changed = metadata != original_metadata

            return self.build_result(
                transformation_input,
                metadata=metadata,
                started_at=started_at,
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Metadata transformation failed",
                extra={
                    "message_id": transformation_input.message_id,
                },
            )

            return TransformationOutput(
                transformation=self.name,
                status=TransformationStatus.FAILED,
                text=transformation_input.text,
                caption=transformation_input.caption,
                changed=False,
                processing_time_ms=elapsed_ms,
                error=str(exc)[:2000],
                metadata={
                    "error_type": type(exc).__name__,
                },
            )
