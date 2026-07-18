"""Immutable metadata container (FEAT-05-6).

Nodes, edges and evidence all carry free-form metadata. We model it as a frozen,
sorted-unique tuple of `(key, value)` items rather than a raw ``dict`` so it is
genuinely immutable (a frozen model with a mutable ``dict`` field would still let
callers mutate the dict in place), deterministic (sorted by key → stable equality,
hashing and serialization), and safe (keys/values are `SafeLabel`/`SafeText`).
``Metadata.from_mapping`` / ``.as_dict`` bridge to ordinary dicts for ergonomics.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, field_validator

from .labels import SafeLabel, SafeText
from .limits import MAX_METADATA_ENTRIES


class MetadataItem(BaseModel):
    """One immutable metadata key/value pair."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: SafeLabel
    value: SafeText


class Metadata(BaseModel):
    """An immutable, deterministic (sorted-unique-by-key) metadata map."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[MetadataItem, ...] = ()

    @field_validator("items")
    @classmethod
    def _sorted_unique(cls, value: tuple[MetadataItem, ...]) -> tuple[MetadataItem, ...]:
        if len(value) > MAX_METADATA_ENTRIES:
            raise ValueError(f"too many metadata entries (max {MAX_METADATA_ENTRIES})")
        seen: dict[str, MetadataItem] = {}
        for item in value:
            if item.key in seen and seen[item.key].value != item.value:
                raise ValueError(f"conflicting metadata values for key {item.key!r}")
            seen[item.key] = item
        return tuple(sorted(seen.values(), key=lambda it: it.key))

    def get(self, key: str) -> str | None:
        """Return the value for `key`, or None. O(n) over a small bounded map."""
        for item in self.items:
            if item.key == key:
                return item.value
        return None

    def as_dict(self) -> dict[str, str]:
        """A plain ``dict`` copy (insertion order = sorted key order)."""
        return {item.key: item.value for item in self.items}

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, str] | None) -> Metadata:
        """Build from an ordinary mapping (or None → empty)."""
        if not mapping:
            return cls()
        return cls(items=tuple(MetadataItem(key=k, value=v) for k, v in mapping.items()))


EMPTY_METADATA = Metadata()
