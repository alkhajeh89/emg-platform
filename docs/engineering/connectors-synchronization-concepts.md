# Synchronization Concepts (EPIC-13 / FEAT-13-1)

The framework models **what synchronization a connector supports and how it is
requested** — as contracts and immutable value objects. It **runs no
synchronization, opens no connection, and schedules nothing**. A future
orchestration layer (outside this sprint) executes against these contracts.

## Modes

`SynchronizationMode`: `full`, `incremental`.

- **Full** — re-enumerate the whole source dataset.
- **Incremental** — enumerate changes since an opaque cursor/watermark. Requires
  cursor support.

## Contract vs. policy vs. plan

- **`SynchronizationContract`** — a connector's *declaration* of what it supports:
  `supported_modes`, `supports_change_detection`, `supports_delete_detection`,
  `supports_cursor`. Invariant: declaring `incremental` requires `supports_cursor`.
- **`SynchronizationPolicy`** — the immutable *configuration* for a sync: `mode`,
  bounded `batch_size`, `allow_deletes`, and an inert `schedule_hint` (descriptive
  text, **never executed** — the framework has no scheduler).
- **Plans** — the immutable *request* describing one sync intent:
  - `FullSynchronization(connector_id, policy)` — policy mode must be `full`.
  - `IncrementalSynchronization(connector_id, policy, since_cursor)` — policy mode
    must be `incremental`; `since_cursor` is the opaque starting watermark.

## Validation

`ConnectorValidator.validate_synchronization(contract, policy)` returns a
deterministic tuple of issues (empty = valid) and `assert_synchronization` raises
`ConnectorValidationError`. It checks:

- the policy's mode is in the contract's `supported_modes`;
- incremental requires cursor support;
- `allow_deletes` requires the contract to declare delete detection.

## Change data capture

A detected change is modelled by the immutable `ConnectorChange`
(`ChangeType.{create,update,delete}`, `entity_type`, opaque `external_id`,
`occurred_at`, scalar `attributes`). A `ConnectorSnapshot` records a point-in-time
marker (opaque `cursor` + `entity_count`) for full/incremental bookkeeping. These
are shapes a connector or sync engine *produces*; the framework produces none.

## Mapping

During synchronization a connector maps a neutral `SourceRecord` onto neutral
`MappedEntity` / `MappedRelationship` / `MappedMetadata` via the mapper protocols.
The mapped types are deliberately ontology-neutral: a downstream binding (not this
framework) projects them onto the Module 7 ontology, keeping the connector
framework storage- and ontology-independent.

## What is intentionally deferred

Actual sync execution, scheduling, cursors persistence, backpressure, retry, and
transport all belong to a future orchestration/runtime — none are in FEAT-13-1.
This sprint delivers the deterministic contracts those runtimes will target.
