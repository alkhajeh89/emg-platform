"""Organizational domain entities (Module 7 §4, FEAT-05-1).

The minimum Backlog-required Organizational domain: Organization, BusinessUnit,
Person, Role, System, Project, Process. Each is an `Actor` archetype
specialization that pins `entity_type` to a `Literal` (so the type tag cannot be
forged) and adds a few domain attributes. Every one inherits the full governance
envelope from `Entity` (classification, trust_score, provenance_reference,
owner, lifecycle_status, version, effective dating) — required by construction.
"""

from __future__ import annotations

from typing import Literal

from .core import Actor


class Organization(Actor):
    entity_type: Literal["Organization"] = "Organization"
    # Optional domain attributes (required envelope is inherited).
    legal_name: str | None = None
    jurisdiction: str | None = None


class BusinessUnit(Actor):
    entity_type: Literal["BusinessUnit"] = "BusinessUnit"
    organization_id: str | None = None
    unit_code: str | None = None


class Person(Actor):
    entity_type: Literal["Person"] = "Person"
    display_name: str | None = None
    primary_business_unit_id: str | None = None


class Role(Actor):
    entity_type: Literal["Role"] = "Role"
    role_name: str | None = None
    scope: str | None = None


class System(Actor):
    entity_type: Literal["System"] = "System"
    system_name: str | None = None
    hostname: str | None = None


class Project(Actor):
    entity_type: Literal["Project"] = "Project"
    project_name: str | None = None
    sponsor_business_unit_id: str | None = None


class Process(Actor):
    entity_type: Literal["Process"] = "Process"
    process_name: str | None = None
    owning_business_unit_id: str | None = None


ORGANIZATIONAL_ENTITY_TYPES: dict[str, type[Actor]] = {
    "Organization": Organization,
    "BusinessUnit": BusinessUnit,
    "Person": Person,
    "Role": Role,
    "System": System,
    "Project": Project,
    "Process": Process,
}
