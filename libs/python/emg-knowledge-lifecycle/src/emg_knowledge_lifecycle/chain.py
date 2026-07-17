"""Version chains + lineage (FEAT-05-5).

`VersionChain` is an **immutable** collection of a single entity's versions with
pure lineage helpers. It is validated at construction and rejects a structurally
malformed history — mixed entities, duplicate versions, an unresolved/orphaned
parent reference, more than one active version, or a cycle — by raising a typed
`InvalidChainError`. It is not a store: it holds no I/O and performs no
persistence.

The constructor delegates to the **single authoritative O(N) analysis**,
`emg_knowledge_lifecycle.validation.find_chain_issues` (the same algorithm
`LifecycleValidator.validate_chain` reports), so validation is linear in the
number of versions even for a deep chain, and there is no duplicate cycle
algorithm. This constructor validates independently of pydantic instance
re-validation, so it protects against forged/`model_construct` inputs too.
"""

from __future__ import annotations

from emg_errors import NotFoundError
from pydantic import BaseModel, ConfigDict, model_validator

from .errors import InvalidChainError
from .identifiers import VersionIdentifier
from .states import VersionState
from .version import KnowledgeVersion


class VersionChain(BaseModel):
    """An immutable, validated version history for one entity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    versions: tuple[KnowledgeVersion, ...]

    @model_validator(mode="after")
    def _validate(self) -> VersionChain:
        # Single authoritative O(N) analysis (shared with LifecycleValidator).
        from .validation import find_chain_issues

        issues = find_chain_issues(self.versions)
        if issues:
            raise InvalidChainError(issues[0].detail)
        return self

    # --- pure lookup / lineage helpers -------------------------------------

    def get(self, identifier: VersionIdentifier) -> KnowledgeVersion | None:
        for v in self.versions:
            if v.identifier == identifier:
                return v
        return None

    def active(self) -> KnowledgeVersion | None:
        """The single ACTIVE version, or None. (Uniqueness is enforced.)"""
        for v in self.versions:
            if v.state is VersionState.ACTIVE:
                return v
        return None

    def roots(self) -> tuple[KnowledgeVersion, ...]:
        """Versions with no parent, in stable version order."""
        return tuple(sorted((v for v in self.versions if v.parent is None), key=_ver_key))

    def latest(self) -> KnowledgeVersion:
        """The version with the highest version number (deterministic)."""
        return max(self.versions, key=_ver_key)

    def children(self, identifier: VersionIdentifier) -> tuple[KnowledgeVersion, ...]:
        """Direct children of `identifier`, in stable version order."""
        return tuple(sorted((v for v in self.versions if v.parent == identifier), key=_ver_key))

    def lineage(self, identifier: VersionIdentifier) -> tuple[KnowledgeVersion, ...]:
        """The ancestor chain from `identifier` up to its root (inclusive), in
        child->root order. Raises the typed `emg_errors.NotFoundError` if the
        identifier is not in the chain. A `visited` set makes the walk cycle-safe
        even for a chain assembled via `model_construct` (which bypasses the
        constructor's acyclicity check)."""
        by_id = {v.identifier.key: v for v in self.versions}
        start = by_id.get(identifier.key)
        if start is None:
            raise NotFoundError(f"version {identifier.key} is not in this chain")
        out: list[KnowledgeVersion] = []
        visited: set[str] = set()
        current: KnowledgeVersion | None = start
        while current is not None and current.identifier.key not in visited:
            out.append(current)
            visited.add(current.identifier.key)
            current = by_id.get(current.parent.key) if current.parent is not None else None
        return tuple(out)


def _ver_key(v: KnowledgeVersion) -> tuple[str, int]:
    return v.identifier.sort_key
