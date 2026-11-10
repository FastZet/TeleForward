"""
TeleForward classifier registry.

Maintains registered classifiers and provides controlled lookup,
registration and execution-order management.
"""

from __future__ import annotations

import logging
from typing import Iterable

from app.services.classification.base import BaseClassifier


logger = logging.getLogger(__name__)


class ClassifierRegistryError(Exception):
    """Base exception for classifier registry errors."""


class DuplicateClassifierError(ClassifierRegistryError):
    """Raised when a classifier name is already registered."""


class ClassifierNotFoundError(ClassifierRegistryError):
    """Raised when a requested classifier is not registered."""


class ClassifierRegistry:
    """Central registry for message classifiers."""

    def __init__(self) -> None:
        self._classifiers: dict[str, BaseClassifier] = {}
        self._execution_order: list[str] = []

    @staticmethod
    def _validate_name(name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Classifier name cannot be empty.")

        return name.strip().lower()

    def register(
        self,
        classifier: BaseClassifier,
        *,
        replace: bool = False,
    ) -> None:
        """Register a classifier instance."""
        if not isinstance(classifier, BaseClassifier):
            raise TypeError(
                "classifier must inherit from BaseClassifier."
            )

        name = self._validate_name(classifier.name)

        if name in self._classifiers and not replace:
            raise DuplicateClassifierError(
                f"Classifier {name!r} is already registered."
            )

        if name in self._classifiers:
            logger.warning(
                "Replacing registered classifier",
                extra={"classifier": name},
            )
        else:
            self._execution_order.append(name)

        self._classifiers[name] = classifier

        logger.debug(
            "Classifier registered",
            extra={
                "classifier": name,
                "version": classifier.version,
                "enabled": classifier.enabled,
            },
        )

    def register_many(
        self,
        classifiers: Iterable[BaseClassifier],
        *,
        replace: bool = False,
    ) -> None:
        """Register multiple classifiers."""
        items = list(classifiers)
        names = [
            self._validate_name(classifier.name)
            for classifier in items
        ]

        if len(names) != len(set(names)) and not replace:
            raise DuplicateClassifierError(
                "The registration batch contains duplicate names."
            )

        # Validate the entire batch before modifying the registry.
        for classifier in items:
            if not isinstance(classifier, BaseClassifier):
                raise TypeError(
                    "Every classifier must inherit from BaseClassifier."
                )

        if not replace:
            duplicates = set(names) & set(self._classifiers)

            if duplicates:
                raise DuplicateClassifierError(
                    "Already registered: "
                    + ", ".join(sorted(duplicates))
                )

        for classifier in items:
            self.register(classifier, replace=replace)

    def get(self, name: str) -> BaseClassifier:
        """Retrieve a classifier by name."""
        normalised_name = self._validate_name(name)

        try:
            return self._classifiers[normalised_name]
        except KeyError as exc:
            raise ClassifierNotFoundError(
                f"Classifier {normalised_name!r} is not registered."
            ) from exc

    def get_optional(
        self,
        name: str,
    ) -> BaseClassifier | None:
        """Retrieve a classifier without raising when absent."""
        normalised_name = self._validate_name(name)
        return self._classifiers.get(normalised_name)

    def unregister(self, name: str) -> BaseClassifier:
        """Remove and return a registered classifier."""
        normalised_name = self._validate_name(name)

        classifier = self.get(normalised_name)

        del self._classifiers[normalised_name]
        self._execution_order.remove(normalised_name)

        logger.debug(
            "Classifier unregistered",
            extra={"classifier": normalised_name},
        )

        return classifier

    def set_enabled(
        self,
        name: str,
        enabled: bool,
    ) -> None:
        """Enable or disable a registered classifier."""
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean.")

        classifier = self.get(name)
        classifier.enabled = enabled

    def reorder(
        self,
        names: Iterable[str],
    ) -> None:
        """Set the execution order of all registered classifiers."""
        ordered_names = [
            self._validate_name(name)
            for name in names
        ]

        if len(ordered_names) != len(set(ordered_names)):
            raise ValueError(
                "Execution order cannot contain duplicate names."
            )

        if set(ordered_names) != set(self._classifiers):
            raise ValueError(
                "Execution order must contain every registered classifier "
                "exactly once."
            )

        self._execution_order = ordered_names

    def get_all(
        self,
        *,
        enabled_only: bool = False,
    ) -> tuple[BaseClassifier, ...]:
        """Return registered classifiers in execution order."""
        classifiers = (
            self._classifiers[name]
            for name in self._execution_order
        )

        if enabled_only:
            classifiers = (
                classifier
                for classifier in classifiers
                if classifier.enabled
            )

        return tuple(classifiers)

    def names(
        self,
        *,
        enabled_only: bool = False,
    ) -> tuple[str, ...]:
        """Return registered classifier names."""
        return tuple(
            classifier.name
            for classifier in self.get_all(
                enabled_only=enabled_only,
            )
        )

    def contains(self, name: str) -> bool:
        """Check whether a classifier is registered."""
        normalised_name = self._validate_name(name)
        return normalised_name in self._classifiers

    def clear(self) -> None:
        """Remove all registered classifiers."""
        self._classifiers.clear()
        self._execution_order.clear()

    def __len__(self) -> int:
        return len(self._classifiers)

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False

        return name.strip().lower() in self._classifiers

    def __iter__(self):
        return iter(self.get_all())
