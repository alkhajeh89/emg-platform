"""The knowledge version model (FEAT-05-5).

`KnowledgeVersion` is an **immutable** node in a version chain: its identity, its
managed lifecycle `state`, an optional `parent` identifier (parent-child
lineage), its descriptive metadata, and its effective window. It is pure data —
no persistence, no behaviour beyond self-validation. A version never mutates in
place: a correction is a *new* version that supersedes the old one (append-only
history, consistent with Module 6 / the ontology's append-only posture).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from .identifiers import VersionIdentifier
from .metadata import VersionMetadata
from .states import VersionState


class KnowledgeVersion(BaseModel):
    """An immutable version of a knowledge entity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identifier: VersionIdentifier
    state: VersionState
    metadata: VersionMetadata
    parent: VersionIdentifier | None = None
    effective_from: datetime
    effective_to: datetime | None = None

    @model_validator(mode="after")
    def _validate(self) -> KnowledgeVersion:
        # A version cannot be its own parent (a trivial self-cycle).
        if self.parent is not None and self.parent == self.identifier:
            raise ValueError("a version cannot be its own parent")
        # A parent must belong to the same entity (lineage is within one entity).
        if self.parent is not None and self.parent.entity_id != self.identifier.entity_id:
            raise ValueError("parent must reference the same entity_id")
        # A parent must be an earlier version number than the child.
        if self.parent is not None and self.parent.version >= self.identifier.version:
            raise ValueError("parent version must be lower than the child version")
        # The effective window must be well-formed.
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be strictly after effective_from")
        return self

    @property
    def entity_id(self) -> str:
        return self.identifier.entity_id

    @property
    def version(self) -> int:
        return self.identifier.version

    def is_effective_at(self, moment: datetime) -> bool:
        """True if `moment` falls within the version's effective window. Pure; no
        wall-clock read."""
        if moment < self.effective_from:
            return False
        return self.effective_to is None or moment < self.effective_to
