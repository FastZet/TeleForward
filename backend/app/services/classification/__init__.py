"""
TeleForward classification services.

Provides lazy package-level exports for classification primitives,
managers, registries and built-in classifiers.

Lazy imports help prevent unnecessary module loading and reduce
circular-import risks during application initialisation.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    # Base classification interfaces
    "BaseClassifier": (
        ".base",
        "BaseClassifier",
    ),
    "ClassificationInput": (
        ".base",
        "ClassificationInput",
    ),
    "ClassificationLabel": (
        ".base",
        "ClassificationLabel",
    ),
    "ClassificationResult": (
        ".base",
        "ClassificationResult",
    ),
    "ClassificationStatus": (
        ".base",
        "ClassificationStatus",
    ),

    # Registry
    "ClassifierRegistry": (
        ".registry",
        "ClassifierRegistry",
    ),
    "ClassifierRegistryError": (
        ".registry",
        "ClassifierRegistryError",
    ),
    "DuplicateClassifierError": (
        ".registry",
        "DuplicateClassifierError",
    ),
    "ClassifierNotFoundError": (
        ".registry",
        "ClassifierNotFoundError",
    ),

    # Manager
    "ClassificationManager": (
        ".manager",
        "ClassificationManager",
    ),
    "ClassificationSummary": (
        ".manager",
        "ClassificationSummary",
    ),

    # Built-in classifiers
    "KeywordClassifier": (
        ".keyword",
        "KeywordClassifier",
    ),
    "MediaClassifier": (
        ".media",
        "MediaClassifier",
    ),
    "TopicClassifier": (
        ".topic",
        "TopicClassifier",
    ),
    "SentimentClassifier": (
        ".sentiment",
        "SentimentClassifier",
    ),
    "LanguageClassifier": (
        ".language",
        "LanguageClassifier",
    ),
    "EntityClassifier": (
        ".entity",
        "EntityClassifier",
    ),
    "HashtagClassifier": (
        ".hashtag",
        "HashtagClassifier",
    ),
    "URLClassifier": (
        ".url",
        "URLClassifier",
    ),
    "DuplicateClassifier": (
        ".duplicate",
        "DuplicateClassifier",
    ),
    "MetadataClassifier": (
        ".metadata",
        "MetadataClassifier",
    ),
    "ForwardingClassifier": (
        ".forwarding",
        "ForwardingClassifier",
    ),
    "GeoClassifier": (
        ".geo",
        "GeoClassifier",
    ),

    # Default registry factory
    "DefaultClassifierFactoryError": (
        ".registry_defaults",
        "DefaultClassifierFactoryError",
    ),
    "create_default_classifiers": (
        ".registry_defaults",
        "create_default_classifiers",
    ),
    "create_default_registry": (
        ".registry_defaults",
        "create_default_registry",
    ),
}


__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """
    Resolve an exported attribute on first access.

    Raises:
        AttributeError: If the requested name is not exported.
    """
    export = _EXPORTS.get(name)

    if export is None:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        )

    module_name, attribute_name = export

    module = import_module(
        module_name,
        package=__name__,
    )

    value = getattr(module, attribute_name)

    # Cache the resolved attribute in the package namespace.
    globals()[name] = value

    return value


def __dir__() -> list[str]:
    """Expose available lazy exports to introspection tools."""
    return sorted(set(globals()) | set(__all__))
