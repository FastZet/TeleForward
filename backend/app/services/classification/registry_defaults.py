"""
TeleForward default classification registry.

Provides a factory for constructing and registering built-in
message classifiers.

The factory does not execute classification or persist results.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from app.services.classification.base import BaseClassifier
from app.services.classification.registry import (
    ClassifierRegistry,
)
from app.services.classification.duplicate import DuplicateClassifier
from app.services.classification.entity import EntityClassifier
from app.services.classification.forwarding import ForwardingClassifier
from app.services.classification.geo import GeoClassifier
from app.services.classification.hashtag import HashtagClassifier
from app.services.classification.keyword import KeywordClassifier
from app.services.classification.language import LanguageClassifier
from app.services.classification.media import MediaClassifier
from app.services.classification.metadata import MetadataClassifier
from app.services.classification.sentiment import SentimentClassifier
from app.services.classification.topic import TopicClassifier
from app.services.classification.url import URLClassifier


logger = logging.getLogger(__name__)

DEFAULT_CLASSIFIER_NAMES = (
    "keyword",
    "media",
    "topic",
    "sentiment",
    "language",
    "entity",
    "hashtag",
    "url",
    "duplicate",
    "metadata",
    "forwarding",
    "geo",
)

CLASSIFIER_TYPES: dict[str, type[BaseClassifier]] = {
    "keyword": KeywordClassifier,
    "media": MediaClassifier,
    "topic": TopicClassifier,
    "sentiment": SentimentClassifier,
    "language": LanguageClassifier,
    "entity": EntityClassifier,
    "hashtag": HashtagClassifier,
    "url": URLClassifier,
    "duplicate": DuplicateClassifier,
    "metadata": MetadataClassifier,
    "forwarding": ForwardingClassifier,
    "geo": GeoClassifier,
}


class DefaultClassifierFactoryError(Exception):
    """Raised when default classifier construction fails."""


def create_default_classifiers(
    *,
    enabled: Mapping[str, bool] | None = None,
    configurations: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[BaseClassifier]:
    """
    Construct the built-in classifiers.

    Args:
        enabled:
            Optional mapping of classifier names to enabled states.
            Unspecified classifiers are enabled.

        configurations:
            Optional mapping of classifier names to constructor
            keyword arguments.

    Returns:
        A list of configured classifier instances.

    Raises:
        DefaultClassifierFactoryError:
            If a classifier name or configuration is invalid.
    """
    enabled = enabled or {}
    configurations = configurations or {}

    unknown_enabled = set(enabled) - set(CLASSIFIER_TYPES)
    unknown_configurations = (
        set(configurations) - set(CLASSIFIER_TYPES)
    )

    if unknown_enabled:
        raise DefaultClassifierFactoryError(
            "Unknown classifiers in enabled configuration: "
            + ", ".join(sorted(unknown_enabled))
        )

    if unknown_configurations:
        raise DefaultClassifierFactoryError(
            "Unknown classifiers in constructor configuration: "
            + ", ".join(sorted(unknown_configurations))
        )

    classifiers: list[BaseClassifier] = []

    for name in DEFAULT_CLASSIFIER_NAMES:
        classifier_type = CLASSIFIER_TYPES[name]

        classifier_enabled = enabled.get(name, True)

        if not isinstance(classifier_enabled, bool):
            raise DefaultClassifierFactoryError(
                f"Enabled state for '{name}' must be a boolean."
            )

        configuration = configurations.get(name, {})

        if not isinstance(configuration, Mapping):
            raise DefaultClassifierFactoryError(
                f"Configuration for '{name}' must be a mapping."
            )

        constructor_arguments = dict(configuration)
        constructor_arguments["enabled"] = classifier_enabled

        try:
            classifier = classifier_type(
                **constructor_arguments
            )

        except Exception as exc:
            raise DefaultClassifierFactoryError(
                f"Could not initialise classifier '{name}': {exc}"
            ) from exc

        classifiers.append(classifier)

    return classifiers


def create_default_registry(
    *,
    enabled: Mapping[str, bool] | None = None,
    configurations: Mapping[str, Mapping[str, Any]] | None = None,
) -> ClassifierRegistry:
    """
    Create a registry containing all built-in classifiers.

    Registration preserves DEFAULT_CLASSIFIER_NAMES order.
    """
    try:
        classifiers = create_default_classifiers(
            enabled=enabled,
            configurations=configurations,
        )

        registry = ClassifierRegistry()
        registry.register_many(classifiers)

        logger.info(
            "Initialised default classification registry",
            extra={
                "classifier_count": len(classifiers),
                "enabled_count": sum(
                    classifier.enabled
                    for classifier in classifiers
                ),
                "classifiers": [
                    classifier.name
                    for classifier in classifiers
                ],
            },
        )

        return registry

    except Exception as exc:
        raise DefaultClassifierFactoryError(
            f"Could not create default classifier registry: {exc}"
        ) from exc
