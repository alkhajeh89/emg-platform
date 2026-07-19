# Project Understanding

> High-level architectural overview of the EMG Platform.
>
> This document captures the architectural principles, repository responsibilities, design constraints, and system invariants that guide the implementation of the Enterprise Memory Graph (EMG) Platform. It is intended to provide developers and architects with a concise understanding of how the platform is structured and which architectural decisions are considered immutable.

---

# Table of Contents

1. Architecture Summary
2. Design Principles
3. Coding Conventions
4. Layer Boundaries
5. Repository Responsibilities
6. GraphStore Responsibilities
7. RevisionRepository Responsibilities
8. Migration Responsibilities
9. Testing Philosophy
10. Dependency Rules
11. Transaction Rules
12. Concurrency Rules
13. Serialization Rules
14. Architectural Invariants
15. Risks
16. Open Assumptions

---

# Architecture Summary

- **Authoritative Storage**
  PostgreSQL acts as the single authoritative source of truth for the platform, owning the append-only hash-linked revision log, tenant head pointers, and transactional outbox.

- **Serving Projection**
  Neo4j serves purely as a queryable topology projection that is fully rebuildable from PostgreSQL.

- **Write Path Independence**
  Neo4j never participates in the authoritative write path. All commits complete successfully even if Neo4j is unavailable.

- **Read Path & Fallback**
  Read operations prefer Neo4j and automatically fall back to PostgreSQL (`graph_json`) whenever the serving projection is unavailable.

- **Multi-Tenancy Layout**
  Every persisted record in PostgreSQL and every node or relationship in Neo4j contains a mandatory `tenant_id`.

---

# Design Principles

- Storage Technology Independence
- Append-Only Durability
- Fail-Closed Security
- Data Conformance by Construction
- Immutable Revision History
- Storage-Agnostic Domain Model

---

# Coding Conventions

- Library-first architecture.
- Strict typing using `mypy --strict`.
- Formatting via `black`.
- Linting via `ruff`.
- Fully parameterized SQL and Cypher queries.
- Public packages expose typed interfaces using `py.typed`.

---

# Layer Boundaries

## Core Domain

Contains pure business logic inside **emg-memory-graph**.

The domain layer must never depend on:

- PostgreSQL
- Neo4j
- FastAPI
- SQLAlchemy
- Infrastructure

---

## Persistence Boundary

Implemented by **emg-persistence**.

Responsible for:

- Transactions
- Mapping
- Tenant isolation
- Storage adapters
- Compare-and-set updates

---

## Semantic Layer

Responsible for:

- Graph traversal
- Semantic search
- Query planning
- Read orchestration
- Projection fallback

---

# Repository Responsibilities

## Core Directory Breakdown

| Directory | Purpose |
|------------|---------|
| `/libs` | Shared storage-independent libraries |
| `/services` | Deployable backend services |
| `/apps` | User-facing applications |
| `/infra` | Infrastructure as Code |
| `/observability` | Monitoring, dashboards and telemetry |

---

# GraphStore Responsibilities

- Transaction lifecycle management
- Graph diff calculation
- PostgreSQL commit orchestration
- Neo4j projection updates
- Read fallback management
- Tenant isolation

---

# RevisionRepository Responsibilities

Responsible for:

- Tenant head retrieval
- Snapshot loading
- Revision insertion
- Compare-and-set updates
- Historical revision lookup

---

# Migration Responsibilities

- Track schema history.
- Verify SHA-256 checksums.
- Detect dirty migrations.
- Prevent startup after failed migrations.
- Execute PostgreSQL migrations atomically.
- Execute idempotent Neo4j migrations.

---

# Testing Philosophy

The persistence implementation must satisfy exactly the same behavioral contract as the in-memory implementation.

Testing includes:

- Unit tests
- Contract tests
- Integration tests
- Concurrency tests
- Failure injection tests
- Projection recovery tests

Target coverage:

- **95%+**

---

# Dependency Rules

Dependency flow always points inward.

```
Infrastructure
      │
Persistence
      │
Domain
```

Rules:

- Domain knows nothing about storage.
- Persistence depends on abstractions.
- Services compose libraries.
- No circular dependencies.
- External dependencies remain pinned.

---

# Transaction Rules

Each write operation is bounded by a single PostgreSQL transaction.

Responsibilities include:

- Revision append
- Head update
- Outbox registration

Neo4j is never part of the commit transaction.

Once

```python
GraphStore.write()
```

returns successfully, no additional background work is required for the transaction.

---

# Concurrency Rules

## Compare-and-Set

```sql
UPDATE tenant_heads
SET head_revision_number = :new_revision
WHERE head_revision_number = :expected_revision;
```

If zero rows are affected:

```
PersistenceConflictError
```

must be raised.

---

## First Revision

Initialization uses

```sql
INSERT ...
ON CONFLICT (tenant_id)
DO NOTHING;
```

ensuring only one worker creates the first revision.

---

## Projection Catch-up

Projection advancement is strictly monotonic.

Expected progression:

```
R0 → R1 → R2 → R3
```

Skipped revisions are never allowed.

---

## Advisory Locks

Tenant-scoped advisory locks may be used during projection repair to reduce duplicate recovery work.

---

# Serialization Rules

Semantic equality is verified using:

```python
reconstructed.content_hash()
==
authoritative_revision.content_hash()
```

Raw byte equality is intentionally ignored to prevent serializer-specific differences.

Every revision stores the complete graph snapshot to allow constant-time fallback reads.

---

# Architectural Invariants

The following architectural rules are immutable.

They must never change without an approved architecture decision.

- PostgreSQL is the only source of truth.
- Neo4j is always disposable.
- Graph revisions are immutable.
- Revision history is append-only.
- Every committed revision generates exactly one outbox event.
- GraphStore is the only persistence entry point.
- RevisionRepository owns compare-and-set logic.
- Core domain remains storage-independent.
- All persistence operations are tenant-scoped.
- No infrastructure dependency may enter the domain layer.

---

# Risks

| Risk | Impact |
|------|--------|
| Projection lag | Medium |
| Snapshot storage growth | Medium |
| Longer CI execution | Low |
| Migration failures | Medium |
| Projection rebuild duration | Low |

---

# Open Assumptions

- Neo4j Community Edition satisfies Phase 2 requirements.
- Enterprise clustering is deferred to later phases.
- Outbox relay is implemented during Phase 4.
- Projection rebuilds remain deterministic.
- Future architectural decisions must preserve all invariants defined in this document.
