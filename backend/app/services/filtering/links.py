"""
TeleForward URL and link filtering utilities.

Extracts URLs from message text and evaluates them against configurable
domain, scheme and link-count restrictions.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit


MAX_TEXT_LENGTH = 100_000
MAX_URLS = 1_000
MAX_DOMAIN_LENGTH = 253

URL_PATTERN = re.compile(
    r"""
    (?<![\w@])
    (?:
        https?://
        |
        tg://
        |
        www\.
    )
    [^\s<>"'`]+
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class ExtractedLink:
    """Normalised URL information."""

    original: str
    normalised_url: str
    scheme: str
    hostname: str | None
    domain: str | None
    path: str


@dataclass(frozen=True, slots=True)
class LinkFilterConfig:
    """Configuration for URL filtering."""

    allowed_domains: frozenset[str] = frozenset()
    blocked_domains: frozenset[str] = frozenset()

    allowed_schemes: frozenset[str] = frozenset({
        "http",
        "https",
    })

    min_links: int | None = None
    max_links: int | None = None

    allow_links_without_hostname: bool = False
    match_subdomains: bool = True


@dataclass(frozen=True, slots=True)
class LinkFilterResult:
    """Result of URL filtering."""

    matched: bool
    links: tuple[ExtractedLink, ...]
    blocked_links: tuple[str, ...] = ()
    rejected_links: tuple[str, ...] = ()
    reason: str | None = None


class LinkFilter:
    """Extract and evaluate URLs in Telegram message text."""

    def extract(self, text: str | None) -> tuple[ExtractedLink, ...]:
        """Extract and normalise URLs from message text."""
        if text is None:
            return ()

        if not isinstance(text, str):
            raise TypeError("Message text must be a string.")

        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError("Message text exceeds the maximum length.")

        results: list[ExtractedLink] = []
        seen: set[str] = set()

        for match in URL_PATTERN.finditer(text):
            candidate = self._trim_url(match.group(0))

            if not candidate:
                continue

            if candidate.lower().startswith("www."):
                candidate = f"https://{candidate}"

            link = self._parse_url(candidate)

            if link is None or link.normalised_url in seen:
                continue

            seen.add(link.normalised_url)
            results.append(link)

            if len(results) > MAX_URLS:
                raise ValueError("Message contains too many URLs.")

        return tuple(results)

    @staticmethod
    def _trim_url(value: str) -> str:
        """Remove punctuation commonly attached to URLs in prose."""
        value = value.rstrip(".,;:!?")

        closing_pairs = {
            ")": "(",
            "]": "[",
            "}": "{",
        }

        for closing, opening in closing_pairs.items():
            while (
                value.endswith(closing)
                and value.count(closing) > value.count(opening)
            ):
                value = value[:-1]

        return value

    def _parse_url(self, value: str) -> ExtractedLink | None:
        """Parse and normalise an extracted URL."""
        try:
            parsed = urlsplit(value)
            scheme = parsed.scheme.lower()

            if scheme not in {"http", "https", "tg"}:
                return None

            # Reject malformed URLs and embedded credentials.
            if parsed.username is not None or parsed.password is not None:
                return None

            if scheme == "tg":
                return ExtractedLink(
                    original=value,
                    normalised_url=value,
                    scheme=scheme,
                    hostname=None,
                    domain=None,
                    path=parsed.path,
                )

            hostname = parsed.hostname

            if not hostname:
                return None

            hostname = hostname.rstrip(".").lower()

            if not hostname or len(hostname) > MAX_DOMAIN_LENGTH:
                return None

            # Validate IP addresses or internationalised domain names.
            try:
                ipaddress.ip_address(hostname)
                domain = hostname
            except ValueError:
                try:
                    hostname = hostname.encode("idna").decode("ascii")
                except UnicodeError:
                    return None

                domain = hostname

            try:
                port = parsed.port
            except ValueError:
                return None

            normalised = f"{scheme}://{hostname}"

            if port is not None:
                normalised += f":{port}"

            normalised += parsed.path or "/"

            if parsed.query:
                normalised += f"?{parsed.query}"

            if parsed.fragment:
                normalised += f"#{parsed.fragment}"

            return ExtractedLink(
                original=value,
                normalised_url=normalised,
                scheme=scheme,
                hostname=hostname,
                domain=domain,
                path=parsed.path,
            )

        except (ValueError, UnicodeError):
            return None

    @staticmethod
    def _normalise_domain(domain: str) -> str:
        """Normalise a domain for allowlist and blocklist matching."""
        if not isinstance(domain, str):
            raise TypeError("Domain must be a string.")

        value = domain.strip().lower().rstrip(".")

        if not value or len(value) > MAX_DOMAIN_LENGTH:
            raise ValueError("Invalid domain.")

        if "://" in value or "/" in value or "@" in value:
            raise ValueError(
                "Domain entries must contain hostnames only."
            )

        if value.startswith("*."):
            value = value[2:]

        try:
            return value.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("Invalid internationalised domain.") from exc

    @classmethod
    def _domain_matches(
        cls,
        hostname: str,
        domains: frozenset[str],
        *,
        match_subdomains: bool,
    ) -> bool:
        """Check exact or subdomain matches."""
        hostname = cls._normalise_domain(hostname)

        for configured_domain in domains:
            domain = cls._normalise_domain(configured_domain)

            if hostname == domain:
                return True

            if (
                match_subdomains
                and hostname.endswith(f".{domain}")
            ):
                return True

        return False

    def matches(
        self,
        text: str | None,
        config: LinkFilterConfig,
    ) -> LinkFilterResult:
        """Evaluate extracted URLs against the supplied configuration."""
        links = self.extract(text)

        if (
            config.min_links is not None
            and (
                isinstance(config.min_links, bool)
                or not isinstance(config.min_links, int)
                or config.min_links < 0
            )
        ):
            raise ValueError("min_links must be a non-negative integer.")

        if (
            config.max_links is not None
            and (
                isinstance(config.max_links, bool)
                or not isinstance(config.max_links, int)
                or config.max_links < 0
            )
        ):
            raise ValueError("max_links must be a non-negative integer.")

        if (
            config.min_links is not None
            and config.max_links is not None
            and config.min_links > config.max_links
        ):
            raise ValueError("min_links cannot exceed max_links.")

        allowed_schemes = frozenset(
            scheme.lower()
            for scheme in config.allowed_schemes
        )

        allowed_domains = frozenset(
            self._normalise_domain(domain)
            for domain in config.allowed_domains
        )

        blocked_domains = frozenset(
            self._normalise_domain(domain)
            for domain in config.blocked_domains
        )

        rejected: list[str] = []
        blocked: list[str] = []

        if config.min_links is not None and len(links) < config.min_links:
            rejected.append(
                f"Minimum link count not met: {len(links)}."
            )

        if config.max_links is not None and len(links) > config.max_links:
            rejected.append(
                f"Maximum link count exceeded: {len(links)}."
            )

        for link in links:
            if link.scheme not in allowed_schemes:
                rejected.append(link.original)
                continue

            if link.hostname is None:
                if not config.allow_links_without_hostname:
                    rejected.append(link.original)
                continue

            if blocked_domains and self._domain_matches(
                link.hostname,
                blocked_domains,
                match_subdomains=config.match_subdomains,
            ):
                blocked.append(link.original)
                continue

            if allowed_domains and not self._domain_matches(
                link.hostname,
                allowed_domains,
                match_subdomains=config.match_subdomains,
            ):
                rejected.append(link.original)

        matched = not blocked and not rejected

        if blocked:
            reason = "Message contains a blocked domain."
        elif rejected:
            reason = "Message violates one or more link restrictions."
        else:
            reason = "All links satisfy the configured restrictions."

        return LinkFilterResult(
            matched=matched,
            links=links,
            blocked_links=tuple(blocked),
            rejected_links=tuple(rejected),
            reason=reason,
        )
