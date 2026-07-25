# /tools — Internal Developer Tooling

Per Engineering Master Plan §3: "internal developer tooling: scaffolding
generators, local environment scripts, and CI helper scripts." Pipeline
definitions here are versioned like any other shared library (Engineering
Master Plan §6).

| Path | Purpose |
| --- | --- |
| `scripts/_venv.sh` | Sourced helper: resolves repo root + `.venv` interpreter paths and the supported-Python check used by the other scripts (not executed directly) |
| `scripts/bootstrap.sh` | One-command local environment setup, invoked by `make bootstrap` (creates `.venv`, installs the dev toolchain + all editable packages, git hooks, `.env`, optional docker infra) |
| `scripts/setup-check.sh` | Non-destructive diagnostic of the local environment, invoked by `make setup-check` |
| `scripts/diagnose_editable_installs.py` | Reproduces CPython `site.py`'s exact `.pth`-processing algorithm to pinpoint why an editable-installed local package fails to import (see `docs/engineering/editable-install-troubleshooting.md`); run automatically by both `make setup-check` and `make bootstrap` |
| `scripts/install-libs.sh` | Installs all `libs/python/*` packages editable in a single resolver pass so proprietary sibling deps resolve locally |
| `scripts/install-services.sh` | Installs all installable `services/*` packages (those with a `pyproject.toml`) editable with dev extras |
| `scripts/build-libs.sh` | Builds all `libs/python/*` packages (sdist + wheel) |
| `scripts/run-lint.sh` / `run-fmt.sh` / `run-tests.sh` | Lint / format / test helpers invoked by the `Makefile`; all use the `.venv` tools and fail with a clear message if `make bootstrap` has not been run |
| `scripts/new-service.sh` | Scaffolding generator for a new backend service directory under `/services` |
| `scripts/dependency-audit.sh` | SCA scan helper (`pip-audit`) |
| `scripts/run-integration-tests.sh` | Integration test entry point (skeleton; services register suites here as they land) |
| `scripts/configure-branch-protection.sh` | Applies branch-protection rules via the GitHub CLI (`make branch-protection`) |
| `scripts/detect_temporal_edge_identity_drift.py` | Read-only analysis of exported MemoryGraph revisions for temporal edge identity drift |
| `ci-templates/service-ci-template.yml` | Reusable workflow template a new service's own CI wires into, per FEAT-01-4 |

> **CI note.** A repository-level CI workflow (`.github/workflows/ci.yml`) and
> repo settings (`.github/settings.yml`) are referenced by `CONTRIBUTING.md`/
> `README.md` as the intended pipeline but are **not present in the repository
> yet**. The lint/test/build/audit scripts above are written to be the single
> source of truth those workflows will call once added, and are fully usable
> locally today via the `Makefile`.

## Temporal edge identity drift detector

The detector validates exported graph revisions without connecting to or writing
to PostgreSQL or Neo4j. It verifies content hashes, classifies legacy `me-*` and
canonical identities, groups logical edge shapes, and optionally compares the
graph with an authoritative relationship inventory. It never repairs data,
creates revisions, rebuilds graphs, or updates projections.

```bash
PYTHONPATH=libs/python/emg-memory-graph/src:libs/python/emg-ontology/src:libs/python/emg-common-types/src \
.venv/bin/python tools/scripts/detect_temporal_edge_identity_drift.py \
  --revision-json exports/tenant-a-revision-7.json \
  --relationships-json exports/tenant-a-relationships.json \
  --tenant-id tenant-a \
  --format human
```

`--revision-json` may be repeated or name a directory of JSON files. A persistence
export contains `tenant_id`, `revision_number`, `content_hash`, and `graph_json`.
A raw graph object containing `nodes` and `edges` is also accepted, although a
missing stored hash produces an `insufficient_evidence` finding.

The inventory is a JSON list, or an object with a `relationships` list. Each item
contains:

```json
{
  "relationship_id": "rel-1#v2",
  "relationship_type": "owns",
  "from_entity_id": "person-1",
  "to_entity_id": "project-1",
  "direction": "directed",
  "effective_from": "2025-02-01T00:00:00Z",
  "effective_to": null,
  "classification": "internal",
  "evidence_identities": ["audit-event-2"],
  "provenance_identity": "audit-event-2",
  "supersedes": "rel-1",
  "superseded_by": null
}
```

Evidence identities may be evidence IDs or locators, but the inventory must use
one scheme consistently. When evidence identities are unavailable, evidence
checks remain explicitly unverifiable.

JSON output has a stable top-level schema:

```json
{
  "exit_code": 0,
  "revisions": [],
  "schema_version": 1
}
```

| Exit code | Meaning |
| --- | --- |
| `0` | Clean |
| `1` | Confirmed mixed, missing, interval, or source/graph drift |
| `2` | Suspected collapse, unverifiable legacy identity, or incomplete evidence |
| `3` | Malformed snapshot, content-hash failure, or operational error |

Code `3` takes precedence over `1`, which takes precedence over `2`. Every
finding includes a machine-readable classification, severity, tenant/revision
context, identity and logical shape where applicable, evidence, explanation,
remediation guidance, and a `confirmed` flag.

Confirmed source-comparison findings are intentionally specific:

| Classification | Meaning |
| --- | --- |
| `confirmed_interval_mismatch` | Edge validity differs from authoritative `effective_from` or `effective_to` |
| `confirmed_relationship_definition_mismatch` | Edge type, direction, endpoints, or classification differs from the authoritative relationship |
| `confirmed_evidence_association_mismatch` | Edge evidence is positively associated with another canonical relationship version |

Each classification maps to exit code `1`. If validity and definition fields
both disagree, separate findings are emitted. Unknown or unmapped evidence
remains `insufficient_evidence` with `confirmed: false`.
