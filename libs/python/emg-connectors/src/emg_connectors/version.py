"""Semantic version + compatibility (FEAT-13-1).

A tiny, pure semantic-version value object and a compatibility range used for
**version compatibility** and **plugin compatibility** checks. No parsing of
arbitrary strings beyond ``major.minor.patch`` digits, no networking, no package
resolution — just deterministic comparison and range containment.

The framework itself has a `FRAMEWORK_VERSION`; a plugin declares the framework
version range it is compatible with, and `PluginCompatibility` checks containment.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Version(BaseModel):
    """An immutable semantic version (major.minor.patch)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    major: int = Field(ge=0, le=1_000_000)
    minor: int = Field(ge=0, le=1_000_000)
    patch: int = Field(ge=0, le=1_000_000)

    @classmethod
    def parse(cls, text: str) -> Version:
        """Parse ``"MAJOR.MINOR.PATCH"`` (digits only). Raises ValueError on any
        other shape — no pre-release/build metadata, no wildcards."""
        parts = text.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError(f"invalid semantic version: {text!r} (expected MAJOR.MINOR.PATCH)")
        major, minor, patch = (int(p) for p in parts)
        return cls(major=major, minor=minor, patch=patch)

    @property
    def key(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __lt__(self, other: Version) -> bool:
        return self.key < other.key

    def __le__(self, other: Version) -> bool:
        return self.key <= other.key

    def is_compatible_with(self, other: Version) -> bool:
        """Same-major, and at least as new in (minor, patch) — the standard
        "consumer requires >= other within the same major" rule."""
        return self.major == other.major and self.key >= other.key


class VersionRange(BaseModel):
    """An immutable inclusive `[minimum, maximum]` version range. `maximum=None`
    means "no upper bound"."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    minimum: Version
    maximum: Version | None = None

    @model_validator(mode="after")
    def _validate(self) -> VersionRange:
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("version range maximum must be >= minimum")
        return self

    def contains(self, version: Version) -> bool:
        """True iff `version` is within the inclusive range. Pure/deterministic."""
        if version < self.minimum:
            return False
        return self.maximum is None or version <= self.maximum


# The connector framework's own version. A plugin declares the framework range it
# supports; PluginCompatibility checks this value against that range.
FRAMEWORK_VERSION = Version(major=1, minor=0, patch=0)
