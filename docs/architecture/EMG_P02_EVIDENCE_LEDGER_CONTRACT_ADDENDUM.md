# EMG P-02 Evidence Ledger Contract Addendum

**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Project Architect
**Status:** Accepted
**Decision Date:** 2026-08-02
**Baseline:** `develop` HEAD

> **Acceptance scope.** Acceptance of this addendum authorizes **only the
> implementation of the `EvidenceLedgerRepository` contract inside
> `emg-persistence`**. It authorizes no ingestion wiring, no API route, no
> worker, no user interface, and no product capability. Nothing here creates
> or amends a product-scope decision.

> **Governing authority.** L3 architecture addendum under GR-001. Governed by
> `PHASE2_ARCHITECTURE.md` ADR-4 and the Product Architecture Freeze §12. It
> amends no accepted ADR and creates no dependency on ADR-027, ADR-028, or
> ADR-030.

---

## A. Authority and scope

**FACT.** P-02 is the absence of an implemented `EvidenceLedgerRepository`.
`libs/python/emg-persistence/src/emg_persistence/` contains no `evidence.py`,
while `PHASE2_ARCHITECTURE.md:130` names that module as the intended location.

**ARCHITECTURE DECISION.** This addendum establishes the minimum binding
contract for the `EvidenceLedgerRepository` so that implementation cannot
invent serialization, integrity, concurrency, or security semantics.

**ARCHITECTURE DECISION.** Every semantic in Section J is normative. No
security-relevant or integrity-relevant behaviour of this repository is
implementation-defined.

## B. Proven constraints

**FACT.** `V001__baseline.sql:58-70` defines `evidence_ledger` with columns
`tenant_id`, `seq bigint`, `evidence_id`, `prev_hash` (nullable), `entry_hash
NOT NULL`, `source`, `locator`, `source_principal`, `captured_at timestamptz`,
`payload jsonb NOT NULL`, and `PRIMARY KEY (tenant_id, seq)`.

**FACT.** `V001__baseline.sql:72-73` creates a **non-unique** index
`ix_evidence_ledger_tenant_evidence ON evidence_ledger (tenant_id,
evidence_id)`. No unique constraint exists on `evidence_id`.

**FACT.** `V001__baseline.sql:56-57` records the table as the "Independent
evidence-ledger capability (ADR-4): defined here, NOT written by the GraphStore
write path. Append-only, hash-chained."

**FACT.** `PHASE2_ARCHITECTURE.md:64` (ADR-4) states `GraphStore.write()`
"receives no evidence objects" and "does not write an evidence ledger"; the
repository is "an independent persistence capability".

**FACT.** `PHASE2_ARCHITECTURE.md:109` states Phase 2 "only defines the ledger
schema + repository capability (ADR-4), it is not wired into
`GraphStore.write`."

**FACT.** `PHASE2_ARCHITECTURE.md:440` lists `EvidenceLedgerRepository` among
internal contracts that are "documented, not public".

**FACT.** `V005__runtime_least_privilege.sql:65-67` grants the runtime role
`emg_knowledge_graph_app` only `SELECT, INSERT` on `evidence_ledger`. No
`UPDATE` and no `DELETE` privilege exists for the runtime role.

**FACT.** `emg_persistence/__init__.py:21-29` exports only `PersistenceSettings`,
the three typed errors, `PostgresNeo4jGraphStore`, and `build_graph_store`.
`OutboxRepository` and `RevisionRepository` are not exported; the package
already treats repositories as internal.

**FACT.** `EvidenceRef` (`emg-memory-graph/evidence.py:30-44`) is a frozen,
`extra="forbid"` Pydantic model with fields `evidence_id`, `source`, `locator`,
`source_principal`, `captured_at`, `description`, `event_id`, `correlation_id`,
`metadata`.

**FACT.** `EvidenceRef.create` (`evidence.py:63`) derives `evidence_id` from
`evidence_id_for(source.value, locator)`. `ids.py:18-22` computes it as SHA-256
over a NUL-joined tuple, truncated to 32 hex characters. The identifier is
therefore **content-addressed and deterministic**: the same source artifact
always yields the same `evidence_id` (`evidence.py:6-8`).

**FACT.** The platform's established hash-chain canonicalization is
`json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
encoded UTF-8 and digested with `hashlib.sha256(...).hexdigest()`
(`emg-audit-pipeline/hashing.py:138, 165`; `custody_hashing.py:60, 85`).

**FACT.** `emg-audit-pipeline/hashing.py:31` defines
`GENESIS_PREV_HASH = "0" * 64` as the `prev_hash` of the first chain entry.

**FACT.** `emg-audit-pipeline/integrity.py:38-41` verifies a chain by
recomputing every entry hash, checking every `prev_hash` link, and requiring
strictly increasing sequence numbers.

**FACT.** `emg-persistence/errors.py:20-40` defines exactly three errors:
`PersistenceError`, `PersistenceConflictError`, `ProjectionLagError`. No
integrity error type exists.

**FACT.** `migrations/runner.py:42, 119-123, 137` enforce checksum immutability
("applied migrations are immutable") and forward-only ordering.

**FACT.** `V004__mutation_ledger.sql:168-181` establishes the platform pattern
for database-enforced append-only tables: a `BEFORE UPDATE OR DELETE` trigger
raising `'% is append-only'`. **`evidence_ledger` has no such trigger.**

## C. Explicit non-goals

**ARCHITECTURE DECISION.** This addendum does not authorize:

- New API routes or transport surfaces.
- Automated ingestion wiring, or any call site that populates the ledger.
- User interfaces, workers, schedulers, or background processes.
- Event-sourcing capability beyond the append-only chain defined here.
- Any coupling to `GraphStore`, the outbox, ADR-027, ADR-028, or ADR-030.

## D. Contract decisions

**ARCHITECTURE DECISION.** The ledger is append-only. The repository defines no
`update`, `delete`, `truncate`, or `repair` operation, and no operation that
alters a persisted row.

**ARCHITECTURE DECISION.** PostgreSQL is the authoritative storage engine
(Freeze §12; `PHASE2_ARCHITECTURE.md:26`). No secondary store is authoritative
for evidence, and no cache may substitute for a ledger read.

**ARCHITECTURE DECISION.** Repository-level authorization and classification
boundaries are resolved normatively in **EL-11**. They are no longer
implementation-defined.

## E. Internal models and repository boundary

**ARCHITECTURE DECISION.** The repository exposes two internal models:

- `EvidenceRef` (imported unchanged from `emg-memory-graph`) — the capture
  input. The repository does not redefine, extend, or subclass it.
- `EvidenceEntry` — the stored state: the `EvidenceRef` plus the
  chain-assigned fields `tenant_id`, `seq`, `prev_hash`, `entry_hash`.

**ARCHITECTURE DECISION.** `EvidenceLedgerRepository` is internal to
`emg-persistence`. It is not added to `emg_persistence.__all__`, matching the
existing treatment of `OutboxRepository` and `RevisionRepository`
(`__init__.py:21-29`) and `PHASE2_ARCHITECTURE.md:440`.

**ARCHITECTURE DECISION.** The repository is defined as a `Protocol` with a
PostgreSQL implementation, following the `OutboxRepository` precedent
(`outbox/repository.py:12-15`).

## F. Transaction and concurrency guarantees

**ARCHITECTURE DECISION.** Every append occurs within one atomic PostgreSQL
transaction. Tail read, sequence assignment, chain-link assignment, hash
computation, and row insert either all commit or all roll back.

**ARCHITECTURE DECISION.** Concurrent sequence arbitration is resolved
normatively in **EL-5**. It is no longer implementation-defined.

## G. Integrity and failure guarantees

**ARCHITECTURE DECISION.** Integrity verification obligations are defined
normatively in **EL-7**; corruption and failure behaviour in **EL-8**; recovery
behaviour in **EL-9**.

## H. Security and tenant isolation

**ARCHITECTURE DECISION.** `tenant_id` is a mandatory predicate on every
statement the repository issues — read and write, without exception. A
repository operation that does not carry a `TenantId` does not exist in this
contract.

**ARCHITECTURE DECISION.** No repository operation accepts a tenant identifier
derived from row content, payload content, or any caller-supplied value other
than the explicit `TenantId` parameter.

---

## J. Architecture decisions

The eleven items formerly listed here as open are resolved below as **EL-1
through EL-11**. Each states the verified facts, separates inference from fact,
compares the minimum viable options, states the consequences, and gives the
normative wording.

### EL-1 — Canonical serialization format

**FACT.** Three canonicalization conventions exist in the repository:
(a) `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
for the audit and custody hash chains (`hashing.py:138`, `custody_hashing.py:60`);
(b) RFC 8785 JCS via `rfc8785.dumps` for the Knowledge Graph command fingerprint
(`services/knowledge-graph/src/emg_knowledge_graph/fingerprint.py:130`);
(c) Pydantic `model_dump_json()` concatenation for graph `content_hash`
(`emg-memory-graph/graph.py:144-152`).

**FACT.** `payload` is a `jsonb` column (`V001__baseline.sql:68`). PostgreSQL
`jsonb` does not preserve key order, insignificant whitespace, or duplicate
keys.

**INFERENCE.** Because `entry_hash` must be recomputable from the *stored* row
for verification to be meaningful, canonicalization must be invariant under
`jsonb` normalization. Convention (c) is unsuitable: it depends on Pydantic
field-declaration order, which `jsonb` destroys. Convention (b) is a
cross-language standard but introduces a third-party dependency into
`emg-persistence` for a payload shape containing no floats, where JCS and (a)
produce identical output. Convention (a) is key-order-independent by
construction (`sort_keys=True`) and is the platform's only convention that has
been applied to a hash chain and security-reviewed.

**Options.** (a) platform hash-chain JSON — consistent, dependency-free,
jsonb-invariant, Python-specific. (b) RFC 8785 — cross-language, new dependency,
no behavioural gain for this payload. (c) Pydantic dump — rejected outright, not
jsonb-invariant.

**Consequences.** Choosing (a) makes the evidence chain byte-comparable in
approach to the audit and custody chains and allows one reviewer to reason about
all three. The residual risk is Python-specificity; it is bounded to zero for
this payload provided no floating-point value is ever hashed, which EL-2 makes
normative.

**DECISION EL-1 — Normative.**
> The canonical serialization of the hashed payload is a single JSON document
> produced by `json.dumps(payload, sort_keys=True, separators=(",", ":"),
> ensure_ascii=False)` and encoded as UTF-8. Keys are ordered lexicographically
> by Unicode code point at every level of nesting; there is no insignificant
> whitespace. The canonical form must be reproducible from the persisted row
> alone and must therefore be invariant under PostgreSQL `jsonb` normalization.
> The hashed payload must contain no floating-point value at any depth; all
> numeric values are integers. `null` is preserved as JSON `null` and is never
> normalized to an absent key or an empty string.

### EL-2 — Hash input fields and ordering

**FACT.** The row's columns are `tenant_id`, `seq`, `evidence_id`, `prev_hash`,
`entry_hash`, `source`, `locator`, `source_principal`, `captured_at`, `payload`
(`V001__baseline.sql:58-70`).

**FACT.** The audit chain hashes every immutable field plus `prev_hash`, and
explicitly includes server-assigned identity and ordering fields "so tampering
with them is detected" (`hashing.py:97-100`). Schema version 3 added `tenant_id`
to the hashed payload (`hashing.py:136-137`).

**FACT.** `EvidenceRef` carries four fields with no promoted column:
`description`, `event_id`, `correlation_id`, `metadata` (`evidence.py:37-43`).

**FACT.** `Metadata` is a sorted-unique tuple of `(key, value)` pairs, not a
dict (`emg-memory-graph/metadata.py:1-8`).

**INFERENCE.** If `payload` held only the residual fields, the row would be a
non-redundant decomposition but the promoted columns would sit outside any
consistency check. If `payload` holds the complete `EvidenceRef` and the hash
covers both the promoted columns and `payload`, then any divergence between a
column and its counterpart inside `payload` is itself tamper-evident. This
achieves without a database trigger what `V004__mutation_ledger.sql:185-201`
achieves for the mutation ledger with one.

**Options.** (i) hash promoted columns only — leaves `description`, `event_id`,
`correlation_id`, and `metadata` unprotected; rejected. (ii) hash `payload` only
— leaves column/payload divergence undetectable; rejected. (iii) hash both —
complete coverage, self-validating decomposition.

**Consequences.** Option (iii) makes every persisted byte of the row except
`entry_hash` itself tamper-evident, including cross-tenant relocation (via
`tenant_id`) and reordering (via `seq`).

**DECISION EL-2 — Normative.**
> `payload` stores the complete canonical representation of the captured
> `EvidenceRef`. The promoted columns `evidence_id`, `source`, `locator`,
> `source_principal`, and `captured_at` are a query projection of that payload
> and must equal their payload counterparts.
>
> `entry_hash` is computed over exactly the following nine top-level keys, and
> no others:
>
> `captured_at`, `evidence_id`, `locator`, `payload`, `prev_hash`, `seq`,
> `source`, `source_principal`, `tenant_id`
>
> `entry_hash` itself is excluded, being the output. Ordering is the
> lexicographic key order EL-1 imposes; no separate declaration order is
> normative.
>
> Value normalization is fixed: `seq` is a JSON integer; `source` is the
> `EvidenceSource` enum `.value` string; every `datetime` — including
> `captured_at` both at top level and inside `payload` — is a canonical UTC
> ISO-8601 string produced by converting an aware value to UTC and rendering a
> naive value as UTC, matching `emg-audit-pipeline/hashing.py:34-39`; `metadata`
> is rendered as a JSON object of key to value with keys sorted; absent optional
> fields are rendered as JSON `null`, never omitted.
>
> Adding, removing, or renaming a hashed key is a breaking change to chain
> identity and requires a new addendum revision and an explicit versioning
> decision. It must never be done silently.

### EL-3 — Hash algorithm, encoding, and digest representation

**FACT.** SHA-256 over UTF-8 with a lowercase hexadecimal digest is used
uniformly across the platform: `hashing.py:165`, `custody_hashing.py:85`,
`migrations/discovery.py:31-33`, `emg-memory-graph/graph.py:144`,
`emg-ontology/descriptor.py:101`, `services/knowledge-graph/.../fingerprint.py:137`.

**FACT.** `hashlib.sha256(...).hexdigest()` returns 64 lowercase hexadecimal
characters.

**INFERENCE.** No repository evidence suggests SHA-256 is inadequate for
tamper-evidence in this context. Introducing a second algorithm would create
two verification paths without a stated threat that motivates it.

**Options.** (i) SHA-256 hex — platform standard. (ii) SHA-512 or SHA3 — no
stated driver, divergent from every other chain. (iii) Truncated digest — as
used for ids (`ids.py:15`); rejected for integrity, where full width is the
point.

**Consequences.** Uniformity means one verification implementation shape and one
migration path if the platform ever changes primitive. Fixing the *stored
representation* prevents an implementation from persisting raw bytes, base64, or
uppercase hex and silently breaking cross-process comparison.

**DECISION EL-3 — Normative.**
> `entry_hash` and `prev_hash` are SHA-256 digests computed over the UTF-8
> encoding of the EL-1 canonical string. Both are stored and compared as exactly
> 64 lowercase hexadecimal characters (`[0-9a-f]{64}`). No other algorithm,
> encoding, digest width, or letter case is permitted. Digests are never
> truncated. Hash comparison is performed on the full stored string.

### EL-4 — First-entry sequence and `prev_hash` convention

**FACT.** `prev_hash` is nullable in the DDL (`V001__baseline.sql:62`).

**FACT.** The platform's chain convention uses a non-null genesis sentinel:
`GENESIS_PREV_HASH = "0" * 64` (`hashing.py:31`), and `verify_chain` initializes
its expected link to that sentinel (`integrity.py:41`).

**FACT.** The audit store assigns `sequence_number = 1` to the first entry
(`stores.py:310`).

**INFERENCE.** A nullable `prev_hash` creates two representations of "no
predecessor" (SQL `NULL` and a sentinel) and forces every verifier to encode a
special case. A sentinel keeps the hashed payload total: `prev_hash` is always a
64-character string, so EL-1's canonical form has no conditional shape.

**Options.** (i) `prev_hash = NULL` for entry one — uses the DDL's nullability,
but makes the hashed payload's type vary by position and diverges from the
platform verifier. (ii) `prev_hash = "0"*64` — one uniform type, matches
`integrity.py:41`. (iii) `prev_hash = ""` — a third convention with no
precedent; rejected.

**Consequences.** Option (ii) means the ledger never writes `NULL` into
`prev_hash` even though the column permits it. The column's nullability becomes
a schema permission the contract deliberately does not use, and EL-10 records
the corresponding forward-migration option.

**DECISION EL-4 — Normative.**
> Per tenant, `seq` begins at `1` for the first entry and increases by exactly
> `1` for each subsequent entry. `seq` is never zero, never negative, and never
> reused.
>
> The first entry of a tenant's chain has `prev_hash` equal to the genesis
> sentinel: the 64-character string of ASCII zeros, identical to
> `emg-audit-pipeline/hashing.py:31`. Every subsequent entry has `prev_hash`
> equal to the `entry_hash` of the entry at `seq - 1` for the same tenant.
>
> The repository never writes SQL `NULL`, an empty string, or any other
> placeholder into `prev_hash`. Each tenant's chain is independent; there is no
> cross-tenant chain and no global genesis entry.

### EL-5 — Atomic per-tenant sequence guarantee under concurrency

**FACT.** `PRIMARY KEY (tenant_id, seq)` (`V001__baseline.sql:69`) makes a
duplicate `(tenant_id, seq)` pair impossible to commit.

**FACT.** The audit store's Sprint 6 security review found that a `FOR UPDATE`
tail-row lock "did not guarantee this under READ COMMITTED", and the fix
serialized the whole append on a transaction-scoped lock held from tail read
through insert, retaining the uniqueness constraint "as defense-in-depth"
(`stores.py:226-236`).

**INFERENCE (not fact).** The same failure mode applies here: two concurrent
appends for one tenant that read the tail under READ COMMITTED can compute the
same next `seq` and the same `prev_hash`. One would fail on the primary key —
but only after both had already computed a hash against the same predecessor,
which is the condition a chain must exclude. Relying on the primary key alone
converts a correctness property into an error path.

**Options.** (i) Rely on `PRIMARY KEY` plus retry — the chain is never
corrupted, but sequence allocation is a race whose resolution is an exception;
also permits a gap if a caller abandons a retry. (ii) Serialize appends
per tenant for the whole read-assign-insert window, with the primary key as
defense-in-depth — matches the reviewed audit precedent. (iii) Serialize
appends globally — correct but couples unrelated tenants and violates the
isolation intent of a per-tenant chain.

**Consequences.** Option (ii) yields a strictly gapless, strictly increasing
per-tenant sequence and guarantees that no two entries are ever computed against
the same predecessor hash. Scoping serialization *per tenant* keeps one tenant's
append rate independent of another's, which a global scope would not.

**DECISION EL-5 — Normative.**
> Within one tenant, the sequence of operations comprising tail read, `seq`
> assignment, `prev_hash` assignment, `entry_hash` computation, and row insert
> is serialized as a single indivisible unit against all other appends for that
> same tenant. Two concurrent appends for one tenant can never observe the same
> tail, allocate the same `seq`, or link to the same `prev_hash`.
>
> The serialization scope is exactly one tenant. Appends for different tenants
> must not contend with one another.
>
> A committed tenant chain is gapless and strictly increasing: for every
> committed entry with `seq = n` where `n > 1`, an entry with `seq = n - 1`
> exists for that tenant. A failed or rolled-back append consumes no `seq`.
>
> `PRIMARY KEY (tenant_id, seq)` is retained as defense-in-depth only. An
> implementation must not treat the primary-key violation as its allocation
> mechanism.
>
> This addendum does not prescribe the locking mechanism. Any mechanism that
> demonstrably provides the guarantees above under PostgreSQL READ COMMITTED is
> conformant, and the choice is recorded in Section K as an implementation
> detail.

### EL-6 — Duplicate `evidence_id` semantics

**FACT.** `evidence_id` is content-addressed: `evidence_id_for(source.value,
locator)` (`evidence.py:63`, `ids.py:18-22`). The same artifact always yields
the same id (`evidence.py:6-8`).

**FACT.** The index on `(tenant_id, evidence_id)` is **not unique**
(`V001__baseline.sql:72-73`), while the platform demonstrably knows how to
express uniqueness where it wants it — `outbox.idempotency_key text NOT NULL
UNIQUE` (`V001__baseline.sql:49`).

**FACT.** The audit store suppresses a repeat as a no-op keyed on
`(source_principal, event_id)` (`stores.py:340`), where `event_id` is
producer-supplied rather than content-derived (`stores.py:238-243`).

**INFERENCE.** The audit precedent does not transfer. Its key is a
producer-chosen identifier whose repetition means "the same submission,
retried". Here, repetition means "the same artifact, captured again" — a
distinct real-world event with its own `captured_at`, its own
`source_principal`, and its own position in the chain. Suppressing it would make
an append-only ledger silently not append, and would require a
read-before-write existence check inside the append path.

**Options.** (i) Distinct chain entries for every append — the ledger records
capture events; growth is proportional to captures. (ii) Idempotent suppression
on `(tenant_id, evidence_id)` — smaller ledger, but loses the record of
re-capture and contradicts the non-unique index. (iii) Reject a duplicate as an
error — makes legitimate re-capture a failure; no supporting evidence.

**Consequences.** Option (i) preserves the ledger's meaning as a record of
capture acts, keeps the append path free of conditional logic, and matches the
schema as built. The cost is unbounded growth under repeated capture of one
artifact; that is a rate-control concern for the future ingestion layer, not a
ledger semantic. De-duplicated views of evidence remain available at read time
via the existing `(tenant_id, evidence_id)` index.

**DECISION EL-6 — Normative.**
> `evidence_id` is not an idempotency key and confers no uniqueness. Appending
> an `EvidenceRef` whose `evidence_id` already exists for the tenant creates a
> new, distinct ledger entry with its own `seq`, its own `prev_hash`, and its
> own `entry_hash`.
>
> The repository performs no de-duplication, no suppression, and no
> existence check on `evidence_id`. It never rejects an append because the
> `evidence_id` was seen before.
>
> A unique constraint must never be added to `evidence_id` or to
> `(tenant_id, evidence_id)`; doing so would make lawful re-capture fail.
>
> Retrieving the distinct evidence artifacts known to a tenant is a read-side
> projection over `(tenant_id, evidence_id)`, never a write-side constraint.

### EL-7 — Integrity-verification scope

**FACT.** The Draft text of this addendum stated "Integrity verification during
read is mandatory" without defining depth or cost.

**FACT.** `verify_chain` (`integrity.py:38-41`) recomputes every entry hash,
checks every link, and requires strictly increasing sequence numbers over an
ordered list supplied by the caller.

**FACT.** The audit and custody stores expose verification as an explicit,
separate `verify_integrity()` operation (`stores.py:206, 408`;
`custody_store.py:274, 426`) rather than folding it into every read.

**INFERENCE.** Read-time full-chain traversal from genesis is O(n) per read and
becomes unusable as a tenant's chain grows; it would also make the repository's
read latency a function of total history rather than result size. Per-entry hash
recomputation, by contrast, is constant work per returned row and detects any
alteration of that row's own content. Link continuity is a property of a
*range*, so it belongs to a range-scoped operation.

**Options.** (i) Full chain from genesis on every read — maximal detection,
unbounded cost; rejected. (ii) Per-entry recomputation on every read, plus an
explicit bounded chain-verification operation — constant read cost, complete
detection when verification is requested. (iii) No read-time verification, only
an explicit operation — cheapest, but returns unverified rows to callers by
default; contradicts §G.

**Consequences.** Option (ii) makes §G concrete: a caller can never receive a
row whose stored `entry_hash` disagrees with its own content, and link and
ordering breaks are detectable on demand over any range without paying for
history on every query.

**DECISION EL-7 — Normative.**
> Two distinct obligations apply.
>
> **Per-entry verification is mandatory on every read.** Before the repository
> returns any `EvidenceEntry`, it recomputes that entry's `entry_hash` per EL-1,
> EL-2, and EL-3 from the entry's own persisted fields and compares it to the
> stored `entry_hash`. On mismatch the entry is never returned; EL-8 governs the
> outcome. This cost is constant per returned row and independent of chain
> length.
>
> **Chain verification is an explicit, range-scoped operation.** The repository
> provides a verification operation taking a `TenantId` and an inclusive `seq`
> range. It verifies, for that range: every entry's `entry_hash` recomputes;
> every entry's `prev_hash` equals the preceding entry's `entry_hash`; `seq`
> values are strictly increasing with no gap; and, when the range begins at
> `seq = 1`, that the first entry's `prev_hash` is the genesis sentinel. It
> returns a structured report identifying the first failing `seq` and the failure
> kind, following `integrity.py:28-34`.
>
> Chain verification is never performed implicitly on a read path and is never
> triggered automatically by an append.
>
> **Acknowledged limitation.** Hash-chaining detects out-of-band modification;
> it does not prevent it. A sufficiently privileged database principal can
> rewrite a row and every subsequent row. This is the same honest limitation
> recorded at `integrity.py:12-16` and is stated here rather than left implied.

### EL-8 — Corruption and failure behaviour

**FACT.** `emg-persistence/errors.py:20-40` defines `PersistenceError`,
`PersistenceConflictError`, and `ProjectionLagError`. There is no integrity
error type.

**FACT.** `PersistenceConflictError` is documented as raised "*before* any
durable change — the caller should re-open the transaction and retry"
(`errors.py:24-31`).

**INFERENCE.** An integrity failure and a concurrency conflict demand opposite
caller behaviour: a conflict is retryable, a detected corruption never is.
Mapping corruption onto `PersistenceConflictError` would instruct callers to
retry against corrupt data. A distinct type is therefore required, and it must
derive from `PersistenceError` so existing catch sites remain correct.

**Options.** (i) Reuse `PersistenceError` directly — indistinguishable from
routine failure; rejected. (ii) Reuse `PersistenceConflictError` — actively
harmful, implies retry; rejected. (iii) New `EvidenceLedgerIntegrityError`
deriving from `PersistenceError`.

**Consequences.** Option (iii) gives callers an unambiguous, non-retryable
signal, keeps the package's single-root error convention intact, and makes
"integrity failure" greppable and monitorable as a distinct condition.

**DECISION EL-8 — Normative.**
> The repository raises `EvidenceLedgerIntegrityError`, a new subclass of
> `emg_persistence.errors.PersistenceError`, when a persisted entry fails
> per-entry verification, when a chain link or ordering invariant is violated on
> a path that must return data, or when a stored hash is not 64 lowercase
> hexadecimal characters.
>
> `EvidenceLedgerIntegrityError` is never retryable. The repository never
> retries an operation that raised it, and never downgrades it to a warning, a
> log line, a partial result, or an empty result.
>
> **Fail closed.** On detected corruption the repository returns no data for the
> affected entry. It never returns an unverified entry, never substitutes a
> placeholder, never skips a corrupt entry to continue a page, and never repairs,
> rewrites, deletes, or re-hashes a persisted row.
>
> Concurrency failures remain distinct: contention resolved by EL-5's
> serialization surfaces as `PersistenceConflictError` and is retryable. An
> integrity failure must never be reported as a conflict.
>
> An append that fails for any reason rolls back in full. No partial row, no
> consumed `seq`, and no orphaned chain link may survive a failed append.
>
> Error messages must not embed payload content. Diagnostics identify the
> affected entry by `tenant_id` and `seq` only.

### EL-9 — Recovery and replay behaviour

**FACT.** The ledger is the authoritative record; PostgreSQL is authoritative
(Freeze §12; `PHASE2_ARCHITECTURE.md:26`).

**FACT.** Unlike the graph, which is rebuildable by replay from the revision log
(`PHASE2_ARCHITECTURE.md:26`), the evidence ledger has no upstream source from
which it could be regenerated. Nothing in the repository writes it, and ADR-4
places its future producer outside Phase 2.

**INFERENCE.** "Replay" in the graph sense is undefined here: there is no source
to replay from. Recovery for an append-only evidence chain therefore means
verification and escalation, not reconstruction. Separately, blocking new
appends when a historical break is detected would let an adversary disable
evidence capture entirely by corrupting a single old row — turning a
tamper-*evidence* mechanism into a denial-of-service vector.

**Options.** (i) Reconstruct or re-hash the chain after a detected break —
destroys the evidence that a break occurred; rejected outright. (ii) Append
compensating or corrective entries — creates two truths and invites
interpretation; rejected. (iii) Verify, quarantine the affected range, escalate,
and continue appending against the current stored tail.

**Consequences.** Under option (iii) a break remains permanently detectable at
its original `seq`, later entries continue to chain normally from the stored
tail, and no attacker can suppress capture by corrupting history. The cost is
that entries after a break are chained to a tail that has been altered; the
range verification of EL-7 reports this precisely rather than hiding it.

**DECISION EL-9 — Normative.**
> The ledger is not reconstructible and is never reconstructed. There is no
> replay, rebuild, backfill, re-hash, or chain-repair operation, and none may be
> added by implementation.
>
> Recovery after a failure or a detected break consists of verification and
> escalation only. The repository provides the EL-7 range verification operation
> and nothing further.
>
> A detected break does not block subsequent appends. New entries continue to
> link to the current stored tail so that evidence capture cannot be denied by
> corrupting history. The break remains permanently detectable at its original
> `seq`.
>
> Correcting a mistaken capture is performed by appending a new `EvidenceRef`,
> consistent with `emg-memory-graph/evidence.py:10-11` ("Evidence is *never*
> mutated; correcting evidence means adding a new `EvidenceRef`"). No
> compensating, retracting, or superseding entry type exists in this contract.
>
> Backup and restore are operational concerns outside this addendum. A restored
> ledger is verified with the EL-7 operation before use; restoration confers no
> integrity claim by itself.

### EL-10 — Schema constraints and forward-migration requirements

**FACT.** `V001__baseline.sql:58-73` already provides the primary key and the
non-unique evidence index this contract requires.

**FACT.** `V005__runtime_least_privilege.sql:65-67` grants the runtime role only
`SELECT, INSERT` on `evidence_ledger`, so append-only holds for that role today.

**FACT.** `evidence_ledger` has **no** `BEFORE UPDATE OR DELETE` trigger,
whereas `mutation_ledger` and `mutation_ledger_resource` do
(`V004__mutation_ledger.sql:168-181`). Role grants do not bind the table owner.

**FACT.** `prev_hash` is nullable (`V001__baseline.sql:62`) although EL-4
forbids writing `NULL`.

**FACT.** There is no `CHECK` constraint on `seq >= 1` and none on hash format.

**FACT.** Applied migrations are immutable and ordering is forward-only
(`runner.py:42, 119-123, 137`).

**INFERENCE.** The contract is implementable on `V001` exactly as it stands: the
primary key supplies the uniqueness backstop EL-5 requires as defense-in-depth,
and the grants supply runtime append-only. The missing constraints are hardening
that narrows what a privileged or buggy path can write; they strengthen the
guarantee but are not preconditions for a conformant repository.

**Options.** (i) Require all hardening before any implementation — blocks the
contract on work that changes no repository semantic. (ii) Require none —
leaves the append-only claim resting on grants alone, weaker than the platform's
own `mutation_ledger` standard. (iii) Implement on `V001` now; require the
hardening migration before the ledger is relied upon for evidentiary purposes.

**Consequences.** Option (iii) unblocks the repository contract while making the
hardening an explicit, tracked obligation rather than an omission. It preserves
forward-only migration discipline absolutely.

**DECISION EL-10 — Normative.**
> The `EvidenceLedgerRepository` contract is implementable against
> `V001__baseline.sql` as merged. No schema change is a precondition for
> implementing it.
>
> `V001__baseline.sql` and every other applied migration are immutable and must
> never be edited (`runner.py:119-123`). Every schema change is a new
> forward-only versioned migration.
>
> The following hardening is **required before the ledger is relied upon as an
> evidentiary record**, and is not required to implement the repository
> contract:
>
> 1. A database-enforced append-only guard on `evidence_ledger` rejecting
>    `UPDATE` and `DELETE`, following the pattern already established at
>    `V004__mutation_ledger.sql:168-181`. Role grants alone do not bind the
>    table owner.
> 2. `prev_hash` constrained `NOT NULL`, aligning the column with EL-4. This
>    requires that no `NULL` value exists, which holds by construction for any
>    ledger written under this contract.
> 3. A constraint requiring `seq >= 1`, aligning the column with EL-4.
> 4. Constraints requiring `entry_hash` and `prev_hash` to match
>    `[0-9a-f]{64}`, aligning the columns with EL-3.
>
> No future migration may add a unique constraint on `evidence_id` or
> `(tenant_id, evidence_id)` (EL-6), remove the `PRIMARY KEY (tenant_id, seq)`
> (EL-5), grant `UPDATE` or `DELETE` on `evidence_ledger` to a runtime role
> (Section D), or alter any column that participates in the EL-2 hash input
> without an explicit chain-identity versioning decision recorded in a new
> revision of this addendum.

### EL-11 — Authorization and classification boundaries

**FACT.** The Draft text of this addendum stated that repository-level
authorization and classification enforcement "is outside the scope of this
contract and remains implementation-defined."

**FACT.** `PHASE2_ARCHITECTURE.md:440` classifies `EvidenceLedgerRepository` as
an internal contract, "documented, not public".

**FACT.** The platform's accepted placement for authorization and classification
enforcement is the HTTP/service layer, not the domain or persistence layer:
`services/knowledge-graph/src/emg_knowledge_graph_api/authorization.py` and
`.../classification.py` hold every such decision, and the domain package carries
no principal or authorization concept.

**FACT.** `source_principal` is a field of `EvidenceRef` (`evidence.py:36`) and
is a promoted column (`V001__baseline.sql:66`).

**INFERENCE.** "Implementation-defined" security scope is precisely what this
addendum exists to eliminate, and leaving it would also breach GR-001 Rule 2
(approval status and requirements must be explicit) and Rule 12 (unresolved
conflicts fail closed). Silence is not neutral: an implementer would either
invent an authorization model inside persistence, or assume none exists. Both
outcomes are worse than an explicit exclusion with a named owner. Separately,
`source_principal` records *who captured the evidence*; treating a stored field
as an authorization input would let row content influence an access decision.

**Options.** (i) Enforce authorization in the repository — duplicates the PEP,
contradicts the platform's established placement, and gives persistence a
principal concept it has nowhere else. (ii) Leave it implementation-defined —
prohibited by this addendum's own §A and by GR-001. (iii) Explicitly exclude
authorization and classification from the repository, assign them to the future
service layer, and make tenant isolation a structural invariant rather than an
authorization decision.

**Consequences.** Option (iii) keeps one authorization mechanism in the platform,
keeps the repository free of a principal parameter, and — because the repository
is unexported and has no caller — creates no exposure today. The obligation
transfers explicitly to whichever future service layer wires ingestion, and
Section C already forbids that wiring under this acceptance.

**DECISION EL-11 — Normative.**
> The `EvidenceLedgerRepository` performs **no authorization decision and no
> classification decision**. It has no principal parameter, no clearance
> parameter, no policy dependency, and no Policy Enforcement Point call. This is
> an explicit architectural exclusion, not an unresolved question and not an
> implementation choice.
>
> **Tenant isolation is a structural invariant, not an authorization decision.**
> Every statement the repository issues carries a `tenant_id` predicate bound to
> the explicit `TenantId` parameter. A repository operation without a `TenantId`
> does not exist in this contract. Tenant isolation therefore holds
> unconditionally, independently of any policy configuration, and cannot be
> disabled by misconfiguration.
>
> `source_principal` is recorded evidence content, never an authorization input.
> The repository must not derive, infer, compare, or make any decision from it,
> and must not treat any stored field as an identity or a permission.
>
> Authorization of who may append to, or read from, the evidence ledger, and any
> classification-based filtering of returned entries, are the responsibility of
> the future service layer that wires this capability. They must be resolved by
> the accepted architecture governing that layer **before** any caller is
> connected to this repository. Section C withholds authorization for that
> wiring under this acceptance.
>
> Because the repository is internal and unexported (Section E), no caller
> exists at acceptance and no access-control exposure is created by this
> decision.

---

## I. Acceptance criteria

Each criterion traces to the decisions that justify it. An implementation
satisfying this addendum must demonstrate all of them.

**Serialization and hashing (EL-1, EL-2, EL-3)**

- **AC-1.** The canonical string for a given entry is byte-identical across
  processes, machines, and interpreter restarts. *(EL-1)*
- **AC-2.** The canonical string is reproducible from the persisted row alone
  and is unchanged after a PostgreSQL `jsonb` round trip. *(EL-1)*
- **AC-3.** No floating-point value appears at any depth of the hashed payload.
  *(EL-1)*
- **AC-4.** The hashed payload contains exactly the nine keys EL-2 names, and
  excludes `entry_hash`. *(EL-2)*
- **AC-5.** Altering any promoted column, any field inside `payload`, `seq`,
  `tenant_id`, or `prev_hash` causes recomputation to disagree with the stored
  `entry_hash`. *(EL-2, EL-7)*
- **AC-6.** A divergence between a promoted column and its `payload` counterpart
  is detected by verification. *(EL-2)*
- **AC-7.** `entry_hash` and `prev_hash` are stored as 64 lowercase hexadecimal
  characters; no other representation is accepted or produced. *(EL-3)*
- **AC-8.** Datetimes hash identically whether supplied as aware non-UTC, aware
  UTC, or naive values. *(EL-2)*
- **AC-9.** Absent optional `EvidenceRef` fields hash as JSON `null`, not as an
  omitted key or empty string. *(EL-2)*

**Chain structure (EL-4)**

- **AC-10.** A tenant's first entry has `seq = 1` and `prev_hash` equal to the
  64-character genesis sentinel. *(EL-4)*
- **AC-11.** No entry is ever written with `prev_hash` `NULL` or empty. *(EL-4)*
- **AC-12.** Each entry's `prev_hash` equals the `entry_hash` of that tenant's
  entry at `seq - 1`. *(EL-4)*
- **AC-13.** Two tenants appending independently each begin at `seq = 1` with
  the genesis sentinel; neither chain references the other. *(EL-4, EL-11)*

**Concurrency (EL-5)**

- **AC-14.** Concurrent appends for one tenant produce a strictly increasing,
  gapless `seq` with no duplicate and no two entries sharing a `prev_hash`.
  *(EL-5)*
- **AC-15.** Concurrent appends for different tenants do not contend with one
  another. *(EL-5)*
- **AC-16.** A failed or rolled-back append consumes no `seq` and leaves the
  chain unchanged. *(EL-5, EL-8)*
- **AC-17.** The primary key is never the mechanism by which `seq` is allocated.
  *(EL-5)*

**Duplicate evidence (EL-6)**

- **AC-18.** Appending the same `EvidenceRef` twice produces two entries with
  distinct `seq`, distinct `prev_hash`, and distinct `entry_hash`. *(EL-6)*
- **AC-19.** No append is rejected, suppressed, or de-duplicated on the basis of
  `evidence_id`. *(EL-6)*
- **AC-20.** No unique constraint exists on `evidence_id` or
  `(tenant_id, evidence_id)`. *(EL-6, EL-10)*

**Verification (EL-7)**

- **AC-21.** Every read recomputes the returned entry's `entry_hash` before
  returning it. *(EL-7)*
- **AC-22.** Read cost per returned entry does not grow with chain length.
  *(EL-7)*
- **AC-23.** Range verification detects a mutated field, a broken link, and a
  sequence gap or reordering, and identifies the first failing `seq`. *(EL-7)*
- **AC-24.** Range verification is never invoked implicitly by a read or an
  append. *(EL-7)*

**Failure behaviour (EL-8)**

- **AC-25.** A corrupt entry is never returned in any form — not partially, not
  as a placeholder, and not silently skipped to complete a page. *(EL-8)*
- **AC-26.** Integrity failures raise `EvidenceLedgerIntegrityError`, a subclass
  of `PersistenceError`, and are never retried. *(EL-8)*
- **AC-27.** An integrity failure is never reported as
  `PersistenceConflictError`, and a concurrency conflict is never reported as an
  integrity failure. *(EL-5, EL-8)*
- **AC-28.** No persisted row is repaired, rewritten, deleted, or re-hashed by
  any repository code path. *(EL-8, EL-9)*
- **AC-29.** Error messages carry no payload content and identify entries by
  `tenant_id` and `seq` only. *(EL-8)*

**Recovery (EL-9)**

- **AC-30.** No replay, rebuild, backfill, re-hash, or chain-repair operation
  exists on the repository. *(EL-9)*
- **AC-31.** A detected break does not prevent subsequent appends, and the break
  remains detectable at its original `seq` afterwards. *(EL-9)*

**Schema and migration (EL-10)**

- **AC-32.** The repository operates correctly against `V001__baseline.sql` as
  merged, with no schema change. *(EL-10)*
- **AC-33.** No applied migration file is modified. *(EL-10)*
- **AC-34.** Any hardening constraint is introduced only as a new forward-only
  versioned migration. *(EL-10)*

**Boundaries and security (EL-11, Sections C, D, E, H)**

- **AC-35.** Every statement the repository issues carries a `tenant_id`
  predicate; no operation exists without a `TenantId` parameter. *(EL-11)*
- **AC-36.** No repository signature accepts a principal, clearance, policy, or
  authorization parameter. *(EL-11)*
- **AC-37.** No decision is derived from `source_principal` or any other stored
  field. *(EL-11)*
- **AC-38.** The repository defines no `update`, `delete`, `truncate`, or
  `repair` operation. *(Section D)*
- **AC-39.** `EvidenceLedgerRepository` is not exported from
  `emg_persistence.__all__`. *(Section E)*
- **AC-40.** No code path in `GraphStore`, the outbox, the projection worker,
  ADR-027, ADR-028, or ADR-030 references the evidence ledger, and the evidence
  ledger references none of them. *(Section C, ADR-4)*
- **AC-41.** No API route, ingestion call site, worker, scheduler, or user
  interface is created. *(Section C)*
- **AC-42.** No caller anywhere in the repository invokes
  `EvidenceLedgerRepository` at acceptance. *(Section C, EL-11)*

---

## K. Residual implementation details (non-blocking)

The following are genuinely non-blocking. None carries a security, integrity,
or consistency semantic; each is constrained by an accepted decision above and
may be settled during implementation review without amending this addendum.

1. **Serialization mechanism for EL-5.** Any mechanism providing EL-5's
   guarantees under READ COMMITTED is conformant. A transaction-scoped
   PostgreSQL advisory lock keyed per tenant is the platform's existing reviewed
   approach (`emg-audit-pipeline/stores.py:226-236, 293`) and is the expected
   choice, but this addendum does not mandate it. Whatever is chosen must be
   recorded in the implementation's module docstring.
2. **Retry policy for `PersistenceConflictError`.** Whether the repository
   retries internally or returns the conflict to the caller, and any bound or
   backoff, provided EL-8's non-retryable integrity rule is never violated.
3. **Method names and signatures** of `EvidenceLedgerRepository`, beyond the
   operations EL-7 requires and the operations Section D forbids.
4. **Pagination shape** for range reads and for range verification, provided
   AC-25 holds and no corrupt entry is skipped to fill a page.
5. **Structure of the verification report**, provided it identifies the first
   failing `seq` and the failure kind, following `integrity.py:28-34`.
6. **Placement of the canonical-hashing helpers** within `emg-persistence`
   (a dedicated module versus alongside the repository), provided EL-1 through
   EL-3 are satisfied exactly.
7. **Version number and file name** of the EL-10 hardening migration.
8. **Test-fixture and in-memory double design**, provided any double honours
   EL-4, EL-5, and EL-6 identically to the PostgreSQL implementation.

---

## L. Approval record

- **Status:** Accepted.
- **Decision Date:** 2026-08-02.
- **Owner:** EMG Founder.
- **Architect:** EMG Founder.
- **Decision Authority:** Project Architect.
- **Resolved:** All eleven previously open items are resolved as EL-1 through
  EL-11. No architecture-blocking question remains open, and no
  security-relevant or integrity-relevant behaviour is implementation-defined.
- **Authorizes:** Implementation of the `EvidenceLedgerRepository` contract
  inside `emg-persistence` only.
- **Does not authorize:** Ingestion wiring, API routes, workers, user
  interfaces, event-sourcing capability, or any product capability. Connecting
  any caller to this repository requires the authorization and classification
  decisions named in EL-11 to be resolved first by the accepted architecture
  governing that layer.
