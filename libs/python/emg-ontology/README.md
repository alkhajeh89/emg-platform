# emg-ontology

The **Core Ontology** for Module 7 (Enterprise Knowledge Graph Platform) —
EPIC-05, **FEAT-05-1**, added Sprint 9.

Part of the EMG™ shared-libraries workspace (Module 3, ADR-012), delivered
**library-first** — the same contract-first pattern as `emg-policy-engine` and
`emg-audit-client`. This package defines the *governed ontology model* and a
*conformance layer*; it has **no persistence, no Neo4j binding, no ingestion,
no traversal/query, and no live service**. Those belong to FEAT-05-2 (Knowledge
Ingestion Pipeline) and FEAT-05-4 (Semantic Layer).

## What this is

- **Core archetypes** (`core.py`): an abstract `Entity` and the `Actor`,
  `Artifact`, `Event` archetypes, plus a governed `Relationship` model. Every
  concrete entity requires, **by construction**, the full governance envelope:
  `entity_id`, `entity_type`, `classification` (reused
  `emg_common_types.Classification`), `trust_score`, `provenance_reference`,
  `owner`, `lifecycle_status`, `version`, and effective dating. Models are
  frozen and forbid unknown fields, so mass-assignment and missing-envelope
  writes fail at construction.
- **Organizational domain** (`organizational.py`): Organization, BusinessUnit,
  Person, Role, System, Project, Process.
- **Risk & Safety domain** (`risk_safety.py`): Risk, Control, Policy,
  Regulation, Incident, Evidence.
- **Module-6 reference types** (`references.py`): AuditEventRef,
  ProvenanceRecordRef, CustodyRecordRef — thin *pointers* into the completed
  EPIC-04 Audit Platform. No audit/provenance/custody content is copied
  (single system-of-record).
- **Relationship catalog** (`relationships.py`): HOLDS, OWNED_BY, MITIGATED_BY,
  GOVERNS, REQUIRES, DERIVED_FROM, REFERENCES, IMPACTS — each with source/target
  types, direction, cardinality, mutability, and a self-loop rule.
- **Conformance validator** (`conformance.py`): pure, storage-independent;
  returns typed, machine-readable `ConformanceReport`/`ConformanceError`.
  Rejects unknown entity/relationship types, missing classification / trust
  score / provenance, out-of-range trust score, invalid lifecycle state,
  invalid source/target types, cardinality violations, an edge classification
  below either endpoint, dangling endpoints, prohibited self-loops, invalid
  effective dates, and mass-assigned extra fields.
- **Deterministic descriptor** (`descriptor.py`): the ontology, generated from
  the code models (the models are authoritative — no RDF/OWL/SHACL/YAML), with
  a pinned `ontology_schema_version` and a `descriptor_hash()` guarded by a
  golden test.
- **Audit contract** (`audit.py`): the graph-mutation action names
  (`entity.created`, `entity.superseded`, `relationship.created`,
  `relationship.superseded`) the FEAT-05-2 write path will emit into Module 6.
  Definition only — Sprint 9 emits nothing (no write service).

## What this is not

- **Not a graph store.** Neo4j Enterprise remains the approved future store
  (Master Plan Technology Choice #4); binding it is FEAT-05-2 / FEAT-05-4.
- **Not a trust-scoring engine.** `trust_score` is a required *field*; its
  *calculation* is FEAT-05-3.
- **Not a lifecycle-management engine.** `lifecycle_status` is a validated
  *field*; the managed proposed→active→retired state machine is FEAT-05-5.
- **Not an authorization layer.** Sprint 9 provides classification *tagging by
  construction* only — no PEP integration, no new roles, no clearance-based read
  enforcement.
- **Not a live service.** `services/knowledge-graph` remains scaffolded.

## Usage

```python
from datetime import datetime, timezone
from emg_ontology import Person, ProvenanceReference, new_entity_id, validate_entity

prov = ProvenanceReference(source_principal="emg-svc-identity", event_id="evt-1")
person = Person(
    entity_id=new_entity_id(),
    classification="INTERNAL",
    trust_score=0.9,
    provenance_reference=prov,
    owner="business-unit-1",
    effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
)

# Conformance over a raw candidate "write" (dict) — rejects non-conforming input:
report = validate_entity({"entity_type": "Person", "entity_id": "e1"})
assert not report.ok  # missing classification / trust_score / provenance / owner ...
```
