"""
TeleForward entity filtering utilities.

Provides entity extraction and matching using structured entities supplied
by Telegram adapters or optional NLP providers.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


MAX_ENTITIES = 2_000
MAX_ENTITY_TEXT_LENGTH = 1_000


class EntityType(StrEnum):
    PERSON = "person"
    ORGANISATION = "organisation"
    LOCATION = "location"
    DATE = "date"
    TIME = "time"
    EMAIL = "email"
    PHONE = "phone"
    URL = "url"
    MENTION = "mention"
    HASHTAG = "hashtag"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ExtractedEntity:
    """A structured entity identified in message content."""

    entity_type: EntityType
    value: str
    offset: int | None = None
    length: int | None = None
    source: str = "external"


@dataclass(frozen=True, slots=True)
class EntityFilterConfig:
    """Configuration for entity-based filtering."""

    required_types: frozenset[EntityType] = frozenset()
    allowed_types: frozenset[EntityType] = frozenset()
    blocked_types: frozenset[EntityType] = frozenset()

    required_values: frozenset[str] = frozenset()
    allowed_values: frozenset[str] = frozenset()
    blocked_values: frozenset[str] = frozenset()

    require_all_types: bool = True
    case_sensitive_values: bool = False

    min_entities: int | None = None
    max_entities: int | None = None


@dataclass(frozen=True, slots=True)
class EntityFilterResult:
    """Result of entity filtering."""

    matched: bool
    entities: tuple[ExtractedEntity, ...]
    matched_types: tuple[EntityType, ...]
    matched_values: tuple[str, ...]
    missing_types: tuple[EntityType, ...] = ()
    blocked_entities: tuple[ExtractedEntity, ...] = ()
    rejected_entities: tuple[ExtractedEntity, ...] = ()
    reason: str | None = None


class EntityFilter:
    """Filter structured entities extracted from Telegram messages."""

    EMAIL_PATTERN = re.compile(
        r"(?<![\w.+-])"
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
        r"(?![\w.-])",
        re.UNICODE,
    )

    MENTION_PATTERN = re.compile(
        r"(?<!\w)@([A-Za-z][A-Za-z0-9_]{4,31})"
    )

    HASHTAG_PATTERN = re.compile(
        r"(?<!\w)#([\w]+)",
        re.UNICODE,
    )

    @staticmethod
    def _normalise_value(
        value: str,
        *,
        case_sensitive: bool,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError("Entity values must be strings.")

        normalised = unicodedata.normalize("NFC", value.strip())

        if not normalised:
            raise ValueError("Entity values cannot be empty.")

        if len(normalised) > MAX_ENTITY_TEXT_LENGTH:
            raise ValueError("Entity value exceeds the maximum length.")

        return (
            normalised
            if case_sensitive
            else normalised.casefold()
        )

    @staticmethod
    def _validate_entity(
        entity: ExtractedEntity,
    ) -> None:
        if not isinstance(entity, ExtractedEntity):
            raise TypeError(
                "Every entity must be an ExtractedEntity instance."
            )

        if not isinstance(entity.entity_type, EntityType):
            raise ValueError("Invalid entity type.")

        if not isinstance(entity.value, str) or not entity.value.strip():
            raise ValueError("Entity value cannot be empty.")

        if len(entity.value) > MAX_ENTITY_TEXT_LENGTH:
            raise ValueError("Entity value exceeds the maximum length.")

        if entity.offset is not None and (
            isinstance(entity.offset, bool)
            or not isinstance(entity.offset, int)
            or entity.offset < 0
        ):
            raise ValueError("Entity offset must be a non-negative integer.")

        if entity.length is not None and (
            isinstance(entity.length, bool)
            or not isinstance(entity.length, int)
            or entity.length < 0
        ):
            raise ValueError("Entity length must be a non-negative integer.")

        if entity.offset is not None and entity.length is not None:
            if entity.length == 0:
                raise ValueError("Entity length must be greater than zero.")

        if not isinstance(entity.source, str) or not entity.source.strip():
            raise ValueError("Entity source cannot be empty.")

    def validate_entities(
        self,
        entities: Iterable[ExtractedEntity],
    ) -> tuple[ExtractedEntity, ...]:
        """Validate and materialise an entity collection."""
        if isinstance(entities, (str, bytes)):
            raise TypeError("Entities must be an iterable of entity objects.")

        validated: list[ExtractedEntity] = []

        for entity in entities:
            self._validate_entity(entity)
            validated.append(entity)

            if len(validated) > MAX_ENTITIES:
                raise ValueError("Too many entities supplied.")

        return tuple(validated)

    def extract_basic(
        self,
        text: str | None,
    ) -> tuple[ExtractedEntity, ...]:
        """
        Extract basic entities without an external NLP provider.

        This method recognises email addresses, Telegram-style mentions
        and hashtags. It does not perform named-entity recognition.
        """
        if text is None:
            return ()

        if not isinstance(text, str):
            raise TypeError("Message text must be a string.")

        entities: list[ExtractedEntity] = []

        patterns = (
            (self.EMAIL_PATTERN, EntityType.EMAIL, 0),
            (self.MENTION_PATTERN, EntityType.MENTION, 1),
            (self.HASHTAG_PATTERN, EntityType.HASHTAG, 1),
        )

        for pattern, entity_type, group in patterns:
            for match in pattern.finditer(text):
                value = match.group(group)

                entities.append(
                    ExtractedEntity(
                        entity_type=entity_type,
                        value=value,
                        offset=match.start(group),
                        length=len(value),
                        source="builtin",
                    )
                )

                if len(entities) > MAX_ENTITIES:
                    raise ValueError(
                        "Message contains too many extracted entities."
                    )

        entities.sort(
            key=lambda entity: (
                entity.offset if entity.offset is not None else -1,
                entity.entity_type.value,
            )
        )

        return tuple(entities)

    @staticmethod
    def _validate_config(config: EntityFilterConfig) -> None:
        for field_name in (
            "require_all_types",
            "case_sensitive_values",
        ):
            if not isinstance(getattr(config, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean.")

        for field_name in (
            "required_types",
            "allowed_types",
            "blocked_types",
        ):
            values = getattr(config, field_name)

            if not isinstance(values, (set, frozenset)):
                raise TypeError(f"{field_name} must be a set.")

            if any(
                not isinstance(value, EntityType)
                for value in values
            ):
                raise ValueError(
                    f"{field_name} contains an invalid entity type."
                )

        for field_name in (
            "required_values",
            "allowed_values",
            "blocked_values",
        ):
            values = getattr(config, field_name)

            if not isinstance(values, (set, frozenset)):
                raise TypeError(f"{field_name} must be a set.")

            for value in values:
                EntityFilter._normalise_value(
                    value,
                    case_sensitive=config.case_sensitive_values,
                )

        for field_name in ("min_entities", "max_entities"):
            value = getattr(config, field_name)

            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or value > MAX_ENTITIES
            ):
                raise ValueError(
                    f"{field_name} must be between 0 and {MAX_ENTITIES}."
                )

        if (
            config.min_entities is not None
            and config.max_entities is not None
            and config.min_entities > config.max_entities
        ):
            raise ValueError(
                "min_entities cannot exceed max_entities."
            )

    def matches(
        self,
        entities: Iterable[ExtractedEntity],
        config: EntityFilterConfig,
    ) -> EntityFilterResult:
        """Evaluate structured entities against filtering constraints."""
        self._validate_config(config)
        validated = self.validate_entities(entities)

        present_types = frozenset(
            entity.entity_type for entity in validated
        )

        required_types = config.required_types
        missing_types = required_types - present_types

        if config.require_all_types:
            required_types_matched = not missing_types
        else:
            required_types_matched = (
                not required_types or bool(required_types & present_types)
            )

        blocked_types = tuple(
            entity
            for entity in validated
            if entity.entity_type in config.blocked_types
        )

        rejected_types = tuple(
            entity
            for entity in validated
            if config.allowed_types
            and entity.entity_type not in config.allowed_types
        )

        required_values = {
            self._normalise_value(
                value,
                case_sensitive=config.case_sensitive_values,
            )
            for value in config.required_values
        }

        allowed_values = {
            self._normalise_value(
                value,
                case_sensitive=config.case_sensitive_values,
            )
            for value in config.allowed_values
        }

        blocked_values = {
            self._normalise_value(
                value,
                case_sensitive=config.case_sensitive_values,
            )
            for value in config.blocked_values
        }

        normalised_values = {
            self._normalise_value(
                entity.value,
                case_sensitive=config.case_sensitive_values,
            )
            for entity in validated
        }

        missing_values = required_values - normalised_values

        blocked_entities = tuple(
            entity
            for entity in validated
            if (
                entity.entity_type in config.blocked_types
                or self._normalise_value(
                    entity.value,
                    case_sensitive=config.case_sensitive_values,
                ) in blocked_values
            )
        )

        rejected_entities = tuple(
            entity
            for entity in validated
            if (
                config.allowed_types
                and entity.entity_type not in config.allowed_types
            )
            or (
                config.allowed_values
                and self._normalise_value(
                    entity.value,
                    case_sensitive=config.case_sensitive_values,
                ) not in allowed_values
            )
        )

        count_matched = (
            config.min_entities is None
            or len(validated) >= config.min_entities
        ) and (
            config.max_entities is None
            or len(validated) <= config.max_entities
        )

        matched = (
            required_types_matched
            and not missing_values
            and not blocked_entities
            and not rejected_entities
            and count_matched
        )

        matched_types = tuple(sorted(
            present_types,
            key=lambda value: value.value,
        ))

        matched_values = tuple(sorted(normalised_values))

        if blocked_entities:
            reason = "Message contains blocked entities."
        elif rejected_entities:
            reason = "Message contains entities outside the allowlist."
        elif not required_types_matched or missing_values:
            reason = "Required entities are missing."
        elif not count_matched:
            reason = "Entity count is outside the configured range."
        else:
            reason = "All entity constraints are satisfied."

        return EntityFilterResult(
            matched=matched,
            entities=validated,
            matched_types=matched_types,
            matched_values=matched_values,
            missing_types=tuple(sorted(
                missing_types,
                key=lambda value: value.value,
            )),
            blocked_entities=blocked_entities,
            rejected_entities=rejected_entities,
            reason=reason,
        )
