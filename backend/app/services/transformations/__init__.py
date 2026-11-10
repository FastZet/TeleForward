"""
TeleForward transformation services.

Provides lazy public exports for transformation base classes,
registry, execution engine, and built-in transformations.

Lazy imports help prevent circular dependencies and reduce
unnecessary module initialisation.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any


_EXPORTS: dict[str, tuple[str, str]] = {
    # Base classes and result types
    "BaseTransformation": (
        "app.services.transformations.base",
        "BaseTransformation",
    ),
    "TransformationInput": (
        "app.services.transformations.base",
        "TransformationInput",
    ),
    "TransformationOutput": (
        "app.services.transformations.base",
        "TransformationOutput",
    ),
    "TransformationStatus": (
        "app.services.transformations.base",
        "TransformationStatus",
    ),

    # Registry
    "TransformationRegistry": (
        "app.services.transformations.registry",
        "TransformationRegistry",
    ),

    # Execution engine
    "TransformationEngine": (
        "app.services.transformations.engine",
        "TransformationEngine",
    ),
    "TransformationSummary": (
        "app.services.transformations.engine",
        "TransformationSummary",
    ),

    # Built-in transformations
    "TextTransformation": (
        "app.services.transformations.text",
        "TextTransformation",
    ),
    "PrefixSuffixTransformation": (
        "app.services.transformations.prefix_suffix",
        "PrefixSuffixTransformation",
    ),
    "ReplaceTransformation": (
        "app.services.transformations.replace",
        "ReplaceTransformation",
    ),
    "LinksTransformation": (
        "app.services.transformations.links",
        "LinksTransformation",
    ),
    "HashtagTransformation": (
        "app.services.transformations.hashtags",
        "HashtagTransformation",
    ),
    "FormattingTransformation": (
        "app.services.transformations.formatting",
        "FormattingTransformation",
    ),
    "MetadataTransformation": (
        "app.services.transformations.metadata",
        "MetadataTransformation",
    ),
    "FiltersTransformation": (
        "app.services.transformations.filters",
        "FiltersTransformation",
    ),
    "ForwardingTransformation": (
        "app.services.transformations.forwarding",
        "ForwardingTransformation",
    ),
}


__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve public exports only when they are requested."""
    target = _EXPORTS.get(name)

    if target is None:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        )

    module_path, attribute_name = target
    module = import_module(module_path)

    try:
        value = getattr(module, attribute_name)
    except AttributeError as exc:
        raise ImportError(
            f"Transformation export {name!r} could not be loaded "
            f"from {module_path!r}."
        ) from exc

    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy exports to IDEs and interactive inspection."""
    return sorted(set(globals()) | set(__all__))


if TYPE_CHECKING:
    from app.services.transformations.base import (
        BaseTransformation,
        TransformationInput,
        TransformationOutput,
        TransformationStatus,
    )
    from app.services.transformations.engine import (
        TransformationEngine,
        TransformationSummary,
    )
    from app.services.transformations.filters import FiltersTransformation
    from app.services.transformations.formatting import FormattingTransformation
    from app.services.transformations.forwarding import ForwardingTransformation
    from app.services.transformations.hashtags import HashtagTransformation
    from app.services.transformations.links import LinksTransformation
    from app.services.transformations.metadata import MetadataTransformation
    from app.services.transformations.prefix_suffix import PrefixSuffixTransformation
    from app.services.transformations.registry import TransformationRegistry
    from app.services.transformations.replace import ReplaceTransformation
    from app.services.transformations.text import TextTransformation
