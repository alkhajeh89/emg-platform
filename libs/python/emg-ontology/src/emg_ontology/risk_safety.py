"""Risk & Safety domain entities (Module 7 §4, FEAT-05-1).

The minimum Backlog-required Risk & Safety domain: Risk, Control, Policy,
Regulation, Incident, Evidence. Archetype assignment: Policy/Regulation/Control/
Evidence are `Artifact`s (governed things); Risk is an `Artifact` (a recorded
assessment); Incident is an `Event`. Every one inherits the full governance
envelope by construction.
"""

from __future__ import annotations

from typing import Literal

from .core import Artifact, Event


class Risk(Artifact):
    entity_type: Literal["Risk"] = "Risk"
    title: str | None = None
    # Qualitative severity label only; quantitative risk scoring is a later
    # feature and is intentionally not modeled here.
    severity: str | None = None


class Control(Artifact):
    entity_type: Literal["Control"] = "Control"
    control_name: str | None = None
    control_family: str | None = None


class Policy(Artifact):
    entity_type: Literal["Policy"] = "Policy"
    policy_name: str | None = None
    policy_reference: str | None = None


class Regulation(Artifact):
    entity_type: Literal["Regulation"] = "Regulation"
    regulation_name: str | None = None
    citation: str | None = None


class Incident(Event):
    entity_type: Literal["Incident"] = "Incident"
    summary: str | None = None
    occurred_at: str | None = None


class Evidence(Artifact):
    entity_type: Literal["Evidence"] = "Evidence"
    # Evidence in the ontology is an artifact node; the authoritative digital
    # evidence / chain-of-custody record lives in Module 6 (FEAT-04-3) and is
    # linked by a CustodyRecord REFERENCES Evidence edge — not copied here.
    label: str | None = None
    evidence_kind: str | None = None


RISK_SAFETY_ENTITY_TYPES: dict[str, type] = {
    "Risk": Risk,
    "Control": Control,
    "Policy": Policy,
    "Regulation": Regulation,
    "Incident": Incident,
    "Evidence": Evidence,
}
