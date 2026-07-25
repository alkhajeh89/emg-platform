"""Language and locale value types (ADR-018: Bilingual Enterprise Architecture).

Shared across the ontology, ingestion, API, AI, and frontend layers so that
``source_language``, ``translations``, ``locale``, and
``terminology_reference`` all converge on one canonical representation
instead of each layer inventing its own — the retrofit
``EMG_ADR-018_Bilingual_Enterprise_Architecture.md`` exists to prevent, and
the gap ``PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md`` Section 1 and
``EMG_ADR-019/020/021`` all name as unresolved until this module exists.

No third-party dependency is introduced: this package (``emg-common-types``)
declares no runtime dependencies today, and every other package in the
monorepo depends on it transitively, so these types are deliberately plain
``Enum``/``NamedTuple`` — the same minimalism already used by
``Classification`` and ``CorrelationId`` in this package — rather than a
``pydantic`` model.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple

_REGION_PATTERN = re.compile(r"^[A-Za-z]{2}$")


class LanguageCode(str, Enum):
    """EMG's currently supported operating languages (ADR-018).

    Each value is an ISO 639-1 code that is also a valid BCP 47 primary
    language subtag. This is an **additive-only** enum: adding a language
    beyond Arabic/English is a platform decision (ADR-018 titles itself
    "Bilingual Enterprise Architecture (Arabic + English)"), not something
    calling code should work around by passing an arbitrary string —
    mirroring how ``Classification``'s values are additive-only.
    """

    ARABIC = "ar"
    ENGLISH = "en"


class TextDirection(str, Enum):
    """Presentation directionality (ADR-018 Section 4: Arabic RTL, English LTR).

    Derived from ``LanguageCode`` (see ``Locale.direction``), never stored or
    chosen independently — a Locale cannot be constructed with a
    language/direction mismatch.
    """

    RTL = "rtl"
    LTR = "ltr"


_DIRECTION_BY_LANGUAGE: dict[LanguageCode, TextDirection] = {
    LanguageCode.ARABIC: TextDirection.RTL,
    LanguageCode.ENGLISH: TextDirection.LTR,
}


class Locale(NamedTuple):
    """A supported language plus an optional region subtag (e.g. ``ar-SA``, ``en``).

    Used wherever ``PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md`` Section 1
    places ``locale``: request-scoped presentation/formatting context (API
    contracts, frontend), never persisted onto an ontology entity — that is
    what ``LanguageCode`` alone (as ``source_language``) is for.
    """

    language: LanguageCode
    region: str | None = None

    @property
    def direction(self) -> TextDirection:
        """RTL for Arabic, LTR for English — always derived, never stored."""
        return _DIRECTION_BY_LANGUAGE[self.language]

    @property
    def tag(self) -> str:
        """The BCP 47 tag for this locale, e.g. ``ar-SA`` or ``en``."""
        return f"{self.language.value}-{self.region}" if self.region else self.language.value

    @classmethod
    def parse(cls, tag: str) -> Locale:
        """Parse a BCP 47-style ``language`` or ``language-REGION`` tag.

        This is the allow-listed validation
        ``EMG_ADR-021_ENTERPRISE_API_STRATEGY.md``'s Security Implications
        section requires for any locale/language header value: the language
        subtag must be one of :class:`LanguageCode`'s supported values (an
        unsupported or malformed language raises ``ValueError`` rather than
        being silently accepted), and an optional region subtag must be
        exactly two letters, normalized to uppercase.

        Raises:
            ValueError: if ``tag`` is empty, has more than one ``-``
                separator, names an unsupported language, or has a
                malformed region subtag.
        """
        if not tag:
            msg = "locale tag must not be empty"
            raise ValueError(msg)

        parts = tag.split("-")
        if len(parts) > 2:
            msg = f"malformed locale tag (expected 'language' or 'language-REGION'): {tag!r}"
            raise ValueError(msg)

        language_part = parts[0].lower()
        try:
            language = LanguageCode(language_part)
        except ValueError as exc:
            supported = ", ".join(code.value for code in LanguageCode)
            msg = f"unsupported language {language_part!r} (supported: {supported})"
            raise ValueError(msg) from exc

        region: str | None = None
        if len(parts) == 2:
            region_part = parts[1]
            if not _REGION_PATTERN.match(region_part):
                msg = f"malformed region subtag (expected 2 letters): {region_part!r}"
                raise ValueError(msg)
            region = region_part.upper()

        return cls(language=language, region=region)
