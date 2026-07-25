# Temporal Edge Identity Rollout

## Background

Sprint 3.2.2 corrected ontology-to-memory-graph identity so
`Relationship.relationship_id` becomes `MemoryEdge.edge_id`. Earlier graphs may
use generated `me-*` IDs and may have merged temporal versions sharing a type and
endpoints. Repository evidence does not prove deployed data is affected; tenants
remain **potentially affected** until their persisted revisions are inspected.

The detector in `tools/scripts/detect_temporal_edge_identity_drift.py` is
read-only. It analyzes exported revision JSON and an optional authoritative
relationship inventory. It never repairs a graph, mutates historical revisions,
or writes to PostgreSQL or Neo4j.

## Detector workflow

1. Export each tenant revision with `tenant_id`, `revision_number`,
   `content_hash`, and `graph_json`.
2. Export the complete authoritative relationship inventory.
3. Run the detector in JSON mode and retain its output with the rollout record.
4. Classify the tenant using the decision matrix below.
5. Resolve incomplete source data before approving corrective action.
6. If approved, append a new graph revision. Historical PostgreSQL revisions
   remain immutable.
7. Validate the new revision, then reconcile Neo4j through its separately
   approved projection workflow.

## Tenant classification and source requirements

A tenant is clean only when the revision validates, the content hash matches, and
no identity drift is found. Multiple canonical temporal versions may
legitimately share one logical edge shape.

A safe controlled rebuild requires the full authoritative relationship set:

- canonical ID and relationship type;
- source and target entity IDs and direction;
- complete `effective_from` and `effective_to` values;
- classification;
- version-specific evidence or provenance identity;
- `supersedes` and `superseded_by` links when present.

A collapsed graph edge cannot supply an interval that was lost by an earlier
merge. Unknown evidence locators and incomplete source inventories are
unverifiable, not confirmed corruption.

Source comparison uses three distinct confirmed classifications:

- `confirmed_interval_mismatch` concerns only validity versus authoritative
  `effective_from` and `effective_to`.
- `confirmed_relationship_definition_mismatch` concerns immutable type,
  direction, endpoints, or classification differences.
- `confirmed_evidence_association_mismatch` concerns evidence positively tied to
  the wrong canonical relationship version.

All three produce exit code `1`. Validity and definition disagreements on the
same edge are emitted separately. Evidence is not described as an interval
mismatch unless validity independently differs.

## Conditions for controlled rebuild approval

A rebuild may be approved only when:

- the authoritative source is complete for the tenant and revision scope;
- IDs and validity intervals have been independently validated;
- version-specific evidence can be associated without inference;
- expected `me-*` removals and canonical additions are reviewed;
- construction starts from the full source, not a legacy graph base;
- the result is appended as a new immutable PostgreSQL revision;
- rollback and post-projection validation are documented.

If any condition is unmet, stop and recover the source. Never infer temporal
intervals or rewrite historical graph revisions, graph heads, audit records, or
evidence.

## Neo4j projection notes

PostgreSQL is authoritative. This detector does not inspect or mutate Neo4j.
Projection-only drift should be repaired from a validated PostgreSQL revision
using the separately authorized projection workflow. Replaying a legacy
PostgreSQL snapshot faithfully reproduces legacy identities; projection rebuild
does not correct authoritative graph data.

## Operator decision matrix

| State | Assessment | Required action |
| --- | --- | --- |
| Clean | No drift found | No action |
| Legacy with complete authoritative source | Potentially affected, recoverable | Review a controlled rebuild into a new revision |
| Legacy without authoritative source | Unverifiable | Stop and recover the complete source |
| Mixed legacy and canonical identity | Confirmed drift | Investigate and rebuild from full source after approval |
| Validity mismatch | Confirmed temporal drift | Validate authoritative intervals before action |
| Relationship-definition mismatch | Confirmed definition drift | Investigate type, direction, endpoints, or classification |
| Evidence association mismatch | Confirmed evidence drift | Investigate version-specific evidence mapping |
| Projection-only drift | Projection issue | Repair projection from PostgreSQL; preserve graph history |
| Malformed snapshot or hash mismatch | Integrity incident | Escalate; no automatic repair |
| Suspected collapsed evidence | Potential historical merge | Inspect source versions; never infer intervals |

Exit code `3` (malformed, hash, or operational failure) takes precedence over
code `1` (confirmed drift), which takes precedence over code `2` (suspected or
unverifiable). A zero exit only describes the supplied inputs; it does not prove
an omitted tenant, revision, or relationship is clean.
