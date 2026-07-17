"""The governed relationship catalog (FEAT-05-1).

Defines the minimum relationship types needed for the two approved Sprint 9
domains. The catalog is the authority for which `(relationship_type,
source_type, target_type)` triples are legal, plus each type's cardinality,
mutability, direction, and self-loop rule. Traversal/query execution is out of
scope (FEAT-05-4) — this is purely the *shape* and the rules.

Endpoint types are referenced by their `entity_type` name (strings), so the
catalog does not import the domain model classes (avoids cycles) and can name
types that may not all be modeled yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from .core import Cardinality, Direction, Mutability


@dataclass(frozen=True)
class RelationshipRule:
    """One entry in the relationship catalog."""

    relationship_type: str
    source_types: frozenset[str]
    target_types: frozenset[str]
    cardinality: Cardinality
    mutability: Mutability
    direction: Direction = Direction.DIRECTED
    self_loop_allowed: bool = False
    description: str = ""


def _rule(
    rtype: str,
    sources: list[str],
    targets: list[str],
    cardinality: Cardinality,
    mutability: Mutability,
    *,
    self_loop_allowed: bool = False,
    description: str = "",
) -> RelationshipRule:
    return RelationshipRule(
        relationship_type=rtype,
        source_types=frozenset(sources),
        target_types=frozenset(targets),
        cardinality=cardinality,
        mutability=mutability,
        self_loop_allowed=self_loop_allowed,
        description=description,
    )


# The minimum governed catalog for Sprint 9's two domains. IMPACTS is scoped to
# Risk & Safety sources (Incident/Risk) toward Organizational targets; the
# Decision-as-source form is deliberately deferred with the Decision entity
# (EPIC-08), so no Decision Intelligence semantics leak into FEAT-05-1.
RELATIONSHIP_CATALOG: dict[str, RelationshipRule] = {
    "HOLDS": _rule(
        "HOLDS",
        ["Person"],
        ["Role"],
        Cardinality.MANY_TO_MANY,
        Mutability.APPEND_ONLY,
        description="A person holds a role (effective-dated, append-only).",
    ),
    "OWNED_BY": _rule(
        "OWNED_BY",
        [
            "Organization",
            "Person",
            "Role",
            "System",
            "Project",
            "Process",
            "Risk",
            "Control",
            "Policy",
            "Regulation",
            "Incident",
            "Evidence",
        ],
        ["BusinessUnit"],
        Cardinality.MANY_TO_ONE,
        Mutability.MUTABLE,
        description="An entity is owned by a business unit (effective-dated).",
    ),
    "MITIGATED_BY": _rule(
        "MITIGATED_BY",
        ["Risk"],
        ["Control"],
        Cardinality.MANY_TO_MANY,
        Mutability.MUTABLE,
        description="A risk is mitigated by a control.",
    ),
    "GOVERNS": _rule(
        "GOVERNS",
        ["Policy"],
        ["Process", "System"],
        Cardinality.MANY_TO_MANY,
        Mutability.MUTABLE,
        description="A policy governs a process or system (effective-dated).",
    ),
    "REQUIRES": _rule(
        "REQUIRES",
        ["Regulation"],
        ["Control"],
        Cardinality.MANY_TO_MANY,
        Mutability.MUTABLE,
        description="A regulation requires a control.",
    ),
    "DERIVED_FROM": _rule(
        "DERIVED_FROM",
        ["Evidence"],
        ["System", "Evidence", "Incident"],
        Cardinality.MANY_TO_ONE,
        Mutability.APPEND_ONLY,
        description="Evidence is derived from a source (append-only lineage). "
        "Document as a source type is added when the Document entity lands.",
    ),
    "REFERENCES": _rule(
        "REFERENCES",
        ["CustodyRecordRef", "AuditEventRef", "ProvenanceRecordRef"],
        ["Evidence"],
        Cardinality.MANY_TO_ONE,
        Mutability.APPEND_ONLY,
        description="A Module-6 reference record references an evidence node.",
    ),
    "IMPACTS": _rule(
        "IMPACTS",
        ["Incident", "Risk"],
        ["Project", "Process", "System"],
        Cardinality.MANY_TO_MANY,
        Mutability.APPEND_ONLY,
        description="An incident or risk impacts a project, process, or system.",
    ),
}


def is_known_relationship_type(relationship_type: str) -> bool:
    return relationship_type in RELATIONSHIP_CATALOG
