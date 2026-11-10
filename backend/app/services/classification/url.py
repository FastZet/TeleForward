"""
TeleForward URL classifier.

Extracts and classifies URLs from Telegram message text and captions.
Performs structural validation and extracts URL metadata without
connecting to external websites.
"""

from __future__ import annotations

import logging
import re
import time

from urllib.parse import urlsplit, urlunsplit

from app.services.classification.base import (
    BaseClassifier,
    ClassificationInput,
    ClassificationLabel,
    ClassificationResult,
    ClassificationStatus,
)


logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 100_000
MAX_URL_LENGTH = 2_048
MAX_URLS = 500

URL_PATTERN = re.compile(
    r"(?i)(?:https?://|www\.)[^\s<>\[\]{}\"']+"
)

TRAILING_PUNCTUATION = ".,;:!?)]}\"'"


class URLClassifier(BaseClassifier):
    """Extract and classify URLs in Telegram messages."""

    name = "url"
    version = "1.0.0"

    def __init__(
        self,
        *,
        allowed_schemes: set[str] | frozenset[str] = frozenset(
            {"http", "https"}
        ),
        blocked_domains: set[str] | frozenset[str] | None = None,
        enabled: bool = True,
        minimum_confidence: float = 0.0,
    ) -> None:
        super().__init__(
            enabled=enabled,
            minimum_confidence=minimum_confidence,
        )

        if not isinstance(allowed_schemes, (set, frozenset)):
            raise TypeError(
                "allowed_schemes must be a set or frozenset."
            )

        schemes = {
            scheme.strip().lower()
            for scheme in allowed_schemes
            if isinstance(scheme, str) and scheme.strip()
        }

        if not schemes or not schemes.issubset({"http", "https"}):
            raise ValueError(
                "allowed_schemes must contain http and/or https."
            )

        self.allowed_schemes = frozenset(schemes)

        self.blocked_domains = self._validate_domains(
            blocked_domains
        )

    @staticmethod
    def _validate_domains(
        domains: set[str] | frozenset[str] | None,
    ) -> frozenset[str]:
        """Validate and normalise blocked domain names."""
        if domains is None:
            return frozenset()

        if not isinstance(domains, (set, frozenset)):
            raise TypeError(
                "blocked_domains must be a set or frozenset."
            )

        validated: set[str] = set()

        for domain in domains:
            if not isinstance(domain, str):
                raise TypeError("Domain names must be strings.")

            normalised = domain.strip().lower().rstrip(".")

            if not normalised:
                raise ValueError("Domain names cannot be empty.")

            if "://" in normalised or "/" in normalised:
                raise ValueError(
                    f"Expected a domain name, got {domain!r}."
                )

            try:
                ascii_domain = normalised.encode("idna").decode("ascii")
            except UnicodeError as exc:
                raise ValueError(
                    f"Invalid domain name: {domain!r}."
                ) from exc

            if len(ascii_domain) > 253:
                raise ValueError("Domain name is too long.")

            validated.add(ascii_domain)

        return frozenset(validated)

    @staticmethod
    def _extract_content(
        classification_input: ClassificationInput,
    ) -> str:
        """Combine message text and caption."""
        content = "\n".join(
            value
            for value in (
                classification_input.text,
                classification_input.caption,
            )
            if isinstance(value, str) and value
        )

        return content[:MAX_CONTENT_LENGTH]

    @staticmethod
    def _normalise_candidate(candidate: str) -> str:
        """Remove common trailing punctuation from extracted URLs."""
        return candidate.rstrip(TRAILING_PUNCTUATION)

    def _parse_url(
        self,
        candidate: str,
    ) -> dict[str, str] | None:
        """Parse and structurally validate a URL candidate."""
        candidate = self._normalise_candidate(candidate)

        if not candidate or len(candidate) > MAX_URL_LENGTH:
            return None

        if candidate.lower().startswith("www."):
            candidate = f"https://{candidate}"

        try:
            parsed = urlsplit(candidate)

            scheme = parsed.scheme.lower()

            if scheme not in self.allowed_schemes:
                return None

            if not parsed.hostname:
                return None

            if parsed.username is not None or parsed.password is not None:
                return None

            hostname = parsed.hostname.lower().rstrip(".")

            try:
                ascii_hostname = (
                    hostname.encode("idna").decode("ascii")
                )
            except UnicodeError:
                return None

            if len(ascii_hostname) > 253:
                return None

            if any(
                not label
                or len(label) > 63
                or label.startswith("-")
                or label.endswith("-")
                for label in ascii_hostname.split(".")
            ):
                return None

            try:
                port = parsed.port
            except ValueError:
                return None

            if port is not None and not 1 <= port <= 65535:
                return None

            return {
                "url": urlunsplit(parsed),
                "scheme": scheme,
                "domain": ascii_hostname,
                "path": parsed.path,
                "query": parsed.query,
                "fragment": parsed.fragment,
                "has_query": str(bool(parsed.query)).lower(),
                "has_fragment": str(bool(parsed.fragment)).lower(),
                "has_port": str(port is not None).lower(),
            }

        except (ValueError, UnicodeError):
            return None

    def _is_blocked(self, domain: str) -> bool:
        """Check exact and subdomain matches against the blocklist."""
        return any(
            domain == blocked
            or domain.endswith(f".{blocked}")
            for blocked in self.blocked_domains
        )

    def _extract_urls(
        self,
        content: str,
    ) -> list[dict[str, str]]:
        """Extract unique structurally valid URLs."""
        extracted: list[dict[str, str]] = []
        seen: set[str] = set()

        for match in URL_PATTERN.finditer(content):
            candidate = match.group(0)

            parsed = self._parse_url(candidate)

            if parsed is None:
                continue

            normalised_url = parsed["url"]

            if normalised_url in seen:
                continue

            seen.add(normalised_url)

            if self._is_blocked(parsed["domain"]):
                parsed["blocked"] = "true"
            else:
                parsed["blocked"] = "false"

            extracted.append(parsed)

            if len(extracted) >= MAX_URLS:
                break

        return extracted

    async def classify(
        self,
        classification_input: ClassificationInput,
    ) -> ClassificationResult:
        """Extract and classify URLs in a Telegram message."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                classifier=self.name,
                reason="URL classifier is disabled.",
            )

        try:
            content = self._extract_content(
                classification_input
            )

            if not content.strip():
                return self.skipped_result(
                    classifier=self.name,
                    reason="Message contains no searchable text.",
                )

            urls = self._extract_urls(content)

            allowed_urls = [
                item for item in urls
                if item["blocked"] == "false"
            ]

            blocked_urls = [
                item for item in urls
                if item["blocked"] == "true"
            ]

            labels = ()

            if allowed_urls:
                label = ClassificationLabel(
                    name="url",
                    category="link_type",
                    confidence=1.0,
                )
                labels = self.filter_by_confidence((label,))

            primary_label = labels[0] if labels else None

            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            return ClassificationResult(
                classifier=self.name,
                status=ClassificationStatus.COMPLETED,
                labels=labels,
                primary_label=primary_label,
                confidence=(
                    primary_label.confidence
                    if primary_label
                    else 0.0
                ),
                processing_time_ms=elapsed_ms,
                metadata={
                    "urls": urls,
                    "url_count": len(urls),
                    "allowed_url_count": len(allowed_urls),
                    "blocked_url_count": len(blocked_urls),
                    "domains": sorted({
                        item["domain"]
                        for item in allowed_urls
                    }),
                    "schemes": sorted({
                        item["scheme"]
                        for item in allowed_urls
                    }),
                },
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "URL classification failed",
                extra={
                    "message_id": classification_input.message_id,
                    "classifier": self.name,
                },
            )

            return ClassificationResult(
                classifier=self.name,
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
