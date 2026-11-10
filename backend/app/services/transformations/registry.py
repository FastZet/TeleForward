"""
TeleForward transformation registry.

Maintains registered message transformations and provides
controlled lookup, registration and execution-order management.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from app.services.transformations.base import BaseTransformation


class TransformationRegistryError(Exception):
    """Base exception for transformation registry errors."""


class DuplicateTransformationError(TransformationRegistryError):
    """Raised when a transformation name is already registered."""


class TransformationNotFoundError(TransformationRegistryError):
    """Raised when a requested transformation does not exist."""


class TransformationRegistry:
    """
    Registry for message transformation implementations.

    Transformations are stored by their unique names. Registration
    order is preserved unless explicitly changed.
    """

    def __init__(self) -> None:
        self._transformations: dict[str, BaseTransformation] = {}

    @staticmethod
    def _validate_name(name: str) -> str:
        """Validate and normalise transformation names."""
        if not isinstance(name, str):
            raise TypeError(
                "Transformation name must be a string."
            )

        normalised = name.strip().lower()

        if not normalised:
            raise ValueError(
                "Transformation name cannot be empty."
            )

        if len(normalised) > 128:
            raise ValueError(
                "Transformation name cannot exceed 128 characters."
            )

        return normalised

    @staticmethod
    def _validate_transformation(
        transformation: BaseTransformation,
    ) -> None:
        """Validate a transformation implementation."""
        if not isinstance(transformation, BaseTransformation):
            raise TypeError(
                "transformation must inherit from BaseTransformation."
            )

        if not isinstance(transformation.enabled, bool):
            raise ValueError(
                "Transformation enabled state must be a boolean."
            )

    def register(
        self,
        transformation: BaseTransformation,
        *,
        replace: bool = False,
    ) -> None:
        """Register a transformation implementation."""
        self._validate_transformation(transformation)

        if not isinstance(replace, bool):
            raise TypeError("replace must be a boolean.")

        name = self._validate_name(
            transformation.name
        )

        existing = self._transformations.get(name)

        if existing is not None and not replace:
            raise DuplicateTransformationError(
                f"Transformation '{name}' is already registered."
            )

        self._transformations[name] = transformation

    def register_many(
        self,
        transformations: Iterable[BaseTransformation],
        *,
        replace: bool = False,
    ) -> None:
        """
        Register multiple transformations.

        The input is validated before registry mutation to avoid
        partial registration caused by invalid names or duplicate
        entries within the supplied batch.
        """
        if not isinstance(replace, bool):
            raise TypeError("replace must be a boolean.")

        batch = list(transformations)
        names: list[str] = []

        for transformation in batch:
            self._validate_transformation(transformation)
            names.append(
                self._validate_name(transformation.name)
            )

        if len(names) != len(set(names)):
            raise DuplicateTransformationError(
                "The registration batch contains duplicate names."
            )

        if not replace:
            conflicts = [
                name
                for name in names
                if name in self._transformations
            ]

            if conflicts:
                raise DuplicateTransformationError(
                    "Transformations already registered: "
                    + ", ".join(conflicts)
                )

        for transformation, name in zip(
            batch,
            names,
            strict=True,
        ):
            self._transformations[name] = transformation

    def get(
        self,
        name: str,
    ) -> BaseTransformation:
        """Retrieve a registered transformation."""
        normalised = self._validate_name(name)

        transformation = self._transformations.get(
            normalised
        )

        if transformation is None:
            raise TransformationNotFoundError(
                f"Transformation '{normalised}' was not found."
            )

        return transformation

    def get_optional(
        self,
        name: str,
    ) -> BaseTransformation | None:
        """Retrieve a transformation without raising if absent."""
        normalised = self._validate_name(name)

        return self._transformations.get(normalised)

    def unregister(
        self,
        name: str,
    ) -> BaseTransformation:
        """Remove and return a registered transformation."""
        normalised = self._validate_name(name)

        transformation = self._transformations.pop(
            normalised,
            None,
        )

        if transformation is None:
            raise TransformationNotFoundError(
                f"Transformation '{normalised}' was not found."
            )

        return transformation

    def set_enabled(
        self,
        name: str,
        enabled: bool,
    ) -> BaseTransformation:
        """Enable or disable a registered transformation."""
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a boolean.")

        transformation = self.get(name)
        transformation.enabled = enabled

        return transformation

    def reorder(
        self,
        names: Iterable[str],
    ) -> None:
        """
        Change transformation execution order.

        All registered transformations must appear exactly once.
        """
        requested = [
            self._validate_name(name)
            for name in names
        ]

        if len(requested) != len(set(requested)):
            raise ValueError(
                "Transformation order contains duplicate names."
            )

        if set(requested) != set(self._transformations):
            raise ValueError(
                "Transformation order must contain every registered "
                "transformation exactly once."
            )

        self._transformations = {
            name: self._transformations[name]
            for name in requested
        }

    def get_all(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[BaseTransformation]:
        """Return transformations in execution order."""
        if not isinstance(enabled_only, bool):
            raise TypeError(
                "enabled_only must be a boolean."
            )

        transformations = list(
            self._transformations.values()
        )

        if enabled_only:
            transformations = [
                transformation
                for transformation in transformations
                if transformation.enabled
            ]

        return transformations

    def names(
        self,
        *,
        enabled_only: bool = False,
    ) -> tuple[str, ...]:
        """Return registered transformation names."""
        return tuple(
            transformation.name
            for transformation in self.get_all(
                enabled_only=enabled_only
            )
        )

    def contains(self, name: str) -> bool:
        """Check whether a transformation is registered."""
        normalised = self._validate_name(name)

        return normalised in self._transformations

    def clear(self) -> None:
        """Remove all registered transformations."""
        self._transformations.clear()

    def __len__(self) -> int:
        return len(self._transformations)

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False

        return self._validate_name(name) in self._transformations

    def __iter__(self) -> Iterator[BaseTransformation]:
        return iter(self.get_all())
