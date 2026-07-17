"""Version identity (FEAT-05-5).

`VersionIdentifier` names one version of one knowledge entity: an entity id plus a
monotonic integer version. It is immutable, validated, and has a deterministic
canonical string form used for stable ordering and reporting.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .labels import SafeLabel
from .limits import MAX_VERSION_NUMBER


class VersionIdentifier(BaseModel):
    """An immutable (entity_id, version) pair identifying one knowledge version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: SafeLabel
    version: int = Field(ge=1, le=MAX_VERSION_NUMBER)

    @property
    def key(self) -> str:
        """A stable canonical string form, e.g. ``"ent-abc@3"``. Deterministic;
        usable as a dict key or for sorted, reproducible output."""
        return f"{self.entity_id}@{self.version}"

    @property
    def sort_key(self) -> tuple[str, int]:
        """A total-ordering key for deterministic sorting of identifiers."""
        return (self.entity_id, self.version)
