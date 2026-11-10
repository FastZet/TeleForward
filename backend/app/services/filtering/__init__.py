"""
TeleForward filtering services.

Provides lazy exports for filtering engines, configurations and results.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, str] = {
    # Core engine
    "FilterContext": ".engine",
    "FilterEngine": ".engine",
    "FilterOperator": ".engine",

    # Text
    "TextFilter": ".text",

    # Media
    "MediaFilter": ".media",

    # Sender
    "SenderContext": ".sender",
    "SenderFilter": ".sender",

    # Chat
    "ChatContext": ".chat",
    "ChatFilter": ".chat",

    # Date
    "DateFilter": ".date",
    "DateFilterConfig": ".date",
    "DateFilterResult": ".date",

    # Length
    "LengthFilter": ".length",
    "LengthFilterConfig": ".length",
    "LengthFilterResult": ".length",
    "LengthMetrics": ".length",

    # Links
    "LinkFilter": ".links",
    "LinkFilterConfig": ".links",
    "LinkFilterResult": ".links",
    "ExtractedLink": ".links",

    # Hashtags
    "HashtagFilter": ".hashtags",
    "HashtagFilterConfig": ".hashtags",
    "HashtagFilterResult": ".hashtags",

    # Keywords
    "KeywordFilter": ".keywords",
    "KeywordFilterConfig": ".keywords",
    "KeywordFilterResult": ".keywords",

    # Entities
    "EntityFilter": ".entities",
    "EntityFilterConfig": ".entities",
    "EntityFilterResult": ".entities",
    "EntityType": ".entities",
    "ExtractedEntity": ".entities",

    # Language
    "LanguageFilter": ".language",
    "LanguageFilterConfig": ".language",
    "LanguageFilterResult": ".language",
    "LanguageDetection": ".language",
    "LanguageDetector": ".language",

    # Unified pipeline
    "ForwardingFilterPipeline": ".forwarding",
    "MessageFilterContext": ".forwarding",
    "MessageFilterConfig": ".forwarding",
    "MessageFilterResult": ".forwarding",
    "FilterCheckResult": ".forwarding",
}


__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve public exports only when requested."""
    module_name = _EXPORTS.get(name)

    if module_name is None:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        )

    module = import_module(module_name, package=__name__)
    value = getattr(module, name)

    # Cache resolved exports in the package namespace.
    globals()[name] = value

    return value


def __dir__() -> list[str]:
    """Expose lazy exports to IDEs and interactive inspection."""
    return sorted(set(globals()) | set(__all__))
