"""
TeleForward URL transformation.

Provides configurable URL manipulation for Telegram messages and captions.
"""

from __future__ import annotations

import logging
import re
import time

from urllib.parse import (
    parse_qsl,
    urlencode,
    urlsplit,
    urlunsplit,
)

from app.services.transformations.base import (
    BaseTransformation,
    TransformationInput,
    TransformationOutput,
    TransformationStatus,
)

logger = logging.getLogger(__name__)

MAX_URLS_PER_MESSAGE = 500
MAX_DOMAIN_LENGTH = 253

URL_PATTERN = re.compile(
    r"""(?ix)
    (?<![\w@])
    (?:
        https?://
        |
        www\.
    )
    [^\s<>"']+
    """
)

DEFAULT_TRACKING_PARAMETERS = frozenset({
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
})


class LinksTransformation(BaseTransformation):
    """Transform URLs contained in message text and captions."""

    name = "links"
    version = "1.0.0"

    def __init__(
        self,
        *,
        remove_links: bool = False,
        remove_tracking_parameters: bool = False,
        normalise_scheme: str | None = None,
        remove_www: bool = False,
        domain_replacements: dict[str, str] | None = None,
        blocked_domains: set[str] | None = None,
        allowed_domains: set[str] | None = None,
        preserve_trailing_punctuation: bool = True,
        apply_to_text: bool = True,
        apply_to_caption: bool = True,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)

        if not isinstance(remove_links, bool):
            raise ValueError("remove_links must be a boolean.")

        if not isinstance(remove_tracking_parameters, bool):
            raise ValueError(
                "remove_tracking_parameters must be a boolean."
            )

        if normalise_scheme not in {None, "http", "https"}:
            raise ValueError(
                "normalise_scheme must be None, 'http' or 'https'."
            )

        for name, value in (
            ("remove_www", remove_www),
            ("preserve_trailing_punctuation", preserve_trailing_punctuation),
            ("apply_to_text", apply_to_text),
            ("apply_to_caption", apply_to_caption),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a boolean.")

        self.remove_links = remove_links
        self.remove_tracking_parameters = remove_tracking_parameters
        self.normalise_scheme = normalise_scheme
        self.remove_www = remove_www
        self.preserve_trailing_punctuation = (
            preserve_trailing_punctuation
        )
        self.apply_to_text = apply_to_text
        self.apply_to_caption = apply_to_caption

        self.domain_replacements = self._validate_replacements(
            domain_replacements or {}
        )

        self.blocked_domains = self._validate_domains(
            blocked_domains or set()
        )

        self.allowed_domains = self._validate_domains(
            allowed_domains or set()
        )

    @staticmethod
    def _normalise_domain(domain: str) -> str:
        """Normalise a domain name for comparison."""
        if not isinstance(domain, str):
            raise TypeError("Domain names must be strings.")

        domain = domain.strip().lower().rstrip(".")

        if not domain:
            raise ValueError("Domain cannot be empty.")

        if len(domain) > MAX_DOMAIN_LENGTH:
            raise ValueError("Domain name is too long.")

        if "/" in domain or ":" in domain or "@" in domain:
            raise ValueError("Invalid domain name.")

        try:
            domain = domain.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("Invalid internationalised domain.") from exc

        return domain

    @classmethod
    def _validate_domains(
        cls,
        domains: set[str],
    ) -> frozenset[str]:
        if not isinstance(domains, set):
            raise TypeError("Domain collections must be sets.")

        return frozenset(
            cls._normalise_domain(domain)
            for domain in domains
        )

    @classmethod
    def _validate_replacements(
        cls,
        replacements: dict[str, str],
    ) -> dict[str, str]:
        if not isinstance(replacements, dict):
            raise TypeError(
                "domain_replacements must be a dictionary."
            )

        if len(replacements) > 100:
            raise ValueError(
                "At most 100 domain replacements are allowed."
            )

        result: dict[str, str] = {}

        for source, destination in replacements.items():
            source_domain = cls._normalise_domain(source)
            destination_domain = cls._normalise_domain(destination)

            result[source_domain] = destination_domain

        return result

    @staticmethod
    def _matches_domain(
        domain: str,
        configured_domains: frozenset[str],
    ) -> bool:
        """Match a domain or one of its subdomains."""
        return any(
            domain == configured
            or domain.endswith("." + configured)
            for configured in configured_domains
        )

    @staticmethod
    def _split_punctuation(value: str) -> tuple[str, str]:
        """Separate common trailing punctuation from a URL."""
        punctuation = ".,!?;:)]}"

        index = len(value)

        while index > 0 and value[index - 1] in punctuation:
            index -= 1

        return value[:index], value[index:]

    def _transform_url(self, url: str) -> str:
        """Apply configured operations to a single URL."""
        original = url

        if url.lower().startswith("www."):
            url = "https://" + url

        try:
            parsed = urlsplit(url)

            if parsed.scheme.lower() not in {"http", "https"}:
                return original

            if not parsed.hostname:
                return original

            hostname = self._normalise_domain(parsed.hostname)

            try:
                port = parsed.port
            except ValueError:
                return original

            if port is not None and not 1 <= port <= 65535:
                return original

            if self._matches_domain(
                hostname,
                self.blocked_domains,
            ):
                return ""

            if self.allowed_domains and not self._matches_domain(
                hostname,
                self.allowed_domains,
            ):
                return ""

            if self.remove_links:
                return ""

            replacement = self.domain_replacements.get(hostname)

            if replacement:
                hostname = replacement

            if self.remove_www and hostname.startswith("www."):
                hostname = hostname[4:]

            if self.normalise_scheme:
                scheme = self.normalise_scheme
            else:
                scheme = parsed.scheme.lower()

            netloc = hostname

            if port is not None:
                netloc = f"{netloc}:{port}"

            query = parsed.query

            if self.remove_tracking_parameters:
                query_parameters = parse_qsl(
                    query,
                    keep_blank_values=True,
                )

                query_parameters = [
                    (key, value)
                    for key, value in query_parameters
                    if key.lower() not in DEFAULT_TRACKING_PARAMETERS
                    and not key.lower().startswith("utm_")
                ]

                query = urlencode(
                    query_parameters,
                    doseq=True,
                )

            return urlunsplit((
                scheme,
                netloc,
                parsed.path,
                query,
                parsed.fragment,
            ))

        except (ValueError, UnicodeError):
            return original

    def _transform_content(self, content: str) -> tuple[str, int]:
        """Transform all detected URLs in a content string."""
        if not content:
            return content, 0

        matches = list(URL_PATTERN.finditer(content))

        if len(matches) > MAX_URLS_PER_MESSAGE:
            raise ValueError(
                f"Message contains more than {MAX_URLS_PER_MESSAGE} URLs."
            )

        if not matches:
            return content, 0

        result: list[str] = []
        previous_end = 0
        transformed_count = 0

        for match in matches:
            result.append(content[previous_end:match.start()])

            original_url = match.group(0)

            if self.preserve_trailing_punctuation:
                url, punctuation = self._split_punctuation(
                    original_url
                )
            else:
                url = original_url
                punctuation = ""

            transformed_url = self._transform_url(url)

            if transformed_url != url:
                transformed_count += 1

            result.append(transformed_url)
            result.append(punctuation)

            previous_end = match.end()

        result.append(content[previous_end:])

        return "".join(result), transformed_count

    async def transform(
        self,
        transformation_input: TransformationInput,
    ) -> TransformationOutput:
        """Transform URLs in message text and captions."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                transformation_input,
                reason="Links transformation is disabled.",
            )

        try:
            text = transformation_input.text
            caption = transformation_input.caption

            text_count = 0
            caption_count = 0

            if self.apply_to_text:
                text, text_count = self._transform_content(text)

            if self.apply_to_caption:
                caption, caption_count = self._transform_content(
                    caption
                )

            return self.build_result(
                transformation_input,
                text=text,
                caption=caption,
                metadata={
                    "text_urls_transformed": text_count,
                    "caption_urls_transformed": caption_count,
                    "total_urls_transformed": (
                        text_count + caption_count
                    ),
                    "tracking_parameters_removed": (
                        self.remove_tracking_parameters
                    ),
                    "links_removed": self.remove_links,
                },
                started_at=started_at,
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Links transformation failed",
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
