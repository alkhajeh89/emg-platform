# S8 — Production PREPARE / Ordinary-Rotation Mutation-Construction Layer

**Status: implementation and emulator-tier qualification complete. Real-cloud
qualification NOT performed by this task (see "Real-cloud qualification
plan" below) — described only, not executed, per this task's explicit
instruction.** This closes the specific gap ADR-044 §17 item 1 and the
corresponding half of item 3 record: "the PREPARE/CAS orchestration layer
above `rotationcommit.completeRawCommit` has deliberately not been built
yet" (`spannercommit`'s own package doc, echoed verbatim in
`cmd/recovery-authority`'s S5 scope note). It does not close ADR-044 §17
item 9 (signing administrative independence) — see the accompanying Track G
decision package — and it does not authorize production provisioning,
production genesis, or production approval.

## What was built

| Package | Role |
|---|---|
| `internal/authority/rotationcommit/rotation.go` | `CompleteRotationCommit` — the ordinary-rotation counterpart to the already-existing, already-qualified `CompleteGenesisCommit`. Adds zero new security logic: it calls the same unexported `completeRawCommit`/`buildCommittedPayload` every emulator T1/T9/T13/T14 conformance test already exercises. |
| `internal/authority/rotationprepare` | The PREPARE/CAS layer itself: begins a real read-write transaction, reads the current `authority_head` row, independently compares it against the caller's declared candidate (expected revision, authority epoch, predecessor state digest), and — only if every check passes — builds the real `authority_head`/`authority_transition_history` mutations and the `*spannerpb.CommitRequest`. Refuses (rolls back, never calls Commit) on any mismatch. |
| `internal/authority/rotationexecute` | The ordinary-rotation orchestrator: composes `rotationprepare` + `rotationcommit.CompleteRotationCommit` + the existing `gcswitness`/`epoch` fail-closed state machine, exactly mirroring `bootstrap.ExecuteGenesis`'s shape without importing or modifying it. |
| `cmd/recovery-rotate` | The production CLI entry point. See its own package doc for the authorization-boundary analysis (Track P5) — no HTTP endpoint was added; see "Authorization boundary" below. |

No existing file was modified except `docs/runbooks/RECOVERY_AUTHORITY_PRODUCTION_RECOVERY_RUNBOOK.md` (status wording only) and this evidence directory. `bootstrap`, `rotationcommit`'s frozen functions, `epoch`, `gcswitness`, and every ADR text are byte-for-byte unchanged.

## P1 — Canonical mutation contract, classified

| Behavior | Classification | Basis |
|---|---|---|
| `authority_head`/`authority_transition_history` column layout | SCHEMA_REQUIRED | `scripts/emulator/schema.sql`, independently echoed by `bootstrap/mutations.go` (production) and `conformance/spanneradapter.go` (test) before this task |
| Expected-revision-plus-one invariant | ARCHITECTURE_REQUIRED | `rotation.NewFixedOperation` (already-existing production code) rejects any `proposedRevision != expectedRevision+1` |
| Predecessor-digest-must-match-current-state-digest | ARCHITECTURE_REQUIRED | New in `rotationprepare.Candidate.checkAgainst` — ADR-044 §7's `CONTENT_BINDING`/provenance discipline extended to the pre-commit read |
| Authority-epoch-must-match | ARCHITECTURE_REQUIRED | New in `rotationprepare.Candidate.checkAgainst` |
| `authority_head` write uses `InsertOrUpdate` | ARCHITECTURE_REQUIRED | Ordinary rotation legitimately updates an existing row (unlike genesis's `Insert`-only) |
| `authority_transition_history` write uses `Insert` (never `InsertOrUpdate`) | ARCHITECTURE_REQUIRED + PROVIDER_REQUIRED | Mirrors `bootstrap.GenesisMutations`'s own reasoning: the primary key `(environment_id, resource_incarnation_id, revision_number)` makes a duplicate/stale write fail at the Spanner layer even if the application-level CAS check were bypassed — defense in depth, not merely a style choice |
| Real-write-transaction (not `SingleUseTransaction`) for ordinary rotation | ARCHITECTURE_REQUIRED | Only a read-write transaction spanning the Read and the Commit gives genuine optimistic-concurrency (lock-based) protection against a second, concurrent rotation attempt — genesis has no such requirement because it has no predecessor row to race against |
| A later read never resolves Commit ambiguity | ARCHITECTURE_REQUIRED | Unchanged, frozen `ClassifyCommit`/`completeRawCommit` — `rotationprepare`'s own read happens strictly *before* Commit, never after |

## P2/P3 — Design and implementation

The minimal production PREPARE boundary is `rotationprepare.RotationSpannerClient` (`CreateSession`/`BeginTransaction`/`Read`/`Rollback`), kept structurally separate from `rotationcommit.RawCommitClient` (`Commit` only) — `rotationexecute.SpannerClient` embeds both, satisfied in production by one single raw `spannerpb.SpannerClient` stub (no second connection type). `acceptedRotationContext` remains completely unexported and unreachable outside `rotationcommit`; `rotationprepare` never sees it. No automatic retry exists anywhere in this new code; every RPC (`CreateSession`, `BeginTransaction`, `Read`, `Commit`, `Rollback`) is called exactly once per attempt.

## P4 — Ordinary rotation path

`rotationexecute.ExecuteRotation`: prepare candidate → build mutations/CommitRequest (inside the read-write transaction) → exactly one real Commit attempt → `ClassifyCommit` → `acceptedRotationContext` only on `UnambiguousSuccess` → V2 signing (`buildCommittedPayload`, `DomainRotationCandidate`) → immutable GCS witness write → epoch transition. `bootstrap` (genesis) is never imported by `rotationprepare`, `rotationexecute`, or `cmd/recovery-rotate` — proven at the source level by each package's own boundary test, not merely asserted.

## P5 — Runtime entrypoint and its authorization boundary

See `cmd/recovery-rotate`'s own package doc comment for the full analysis. Summary: this repository has **no established caller-authentication contract for a network-facing administrative mutation endpoint** — verification is deliberately unprivileged (ADR-045 §5), and `signerrpc`'s bearer scheme authenticates a specific known workload, not an arbitrary rotation requester. Genesis itself has never been exposed over a network endpoint either. Per this task's explicit STOP instruction, no new network auth contract was invented. `recovery-rotate` is a CLI; its authorization boundary is the invoking operator's own GCP credentials and whatever operational access control the deployment enforces around who may execute it — identical in kind to the existing `recovery-bootstrap-deployment` principal's own temporary-credential model in `iam/manifest.json`.

**Disclosed, unresolved governance gap:** unlike genesis (`bootstrap.GenesisRequest` requires two independent `Approval` values before `ExecuteGenesis` runs), **no ADR defines a dual-control or approval requirement for ordinary rotations**, and this task did not invent one. Whether ordinary rotations require dual control is an open human-governance question, tracked in the accompanying Track G package, not silently decided here.

## P6 — Adversarial matrix

Full A–O matrix implemented and passing (`internal/authority/rotationprepare/prepare_test.go` for D/F at the unit tier; `internal/authority/rotationexecute/emulator_matrix_test.go` for A/B/C/E/G/H/I/J/K/L/N against the real Cloud Spanner emulator; M and O are disposition/inheritance arguments, not new tests — see the coverage-map comment at the top of `emulator_matrix_test.go` for the exact rationale on each). All pass. **Note:** these emulator-tagged tests share one external emulator process across every package in the module and must be run with `go test -tags=emulator -p1 ./...` (sequential package execution) — this is a pre-existing property of this test tier (the emulator itself, documented in `rotationcommit`'s own tests, "only supports one transaction at a time"), not something this task introduced, and it does not affect CI (the `emulator` build tag is never used by the CI workflow).

## P7 — Real-cloud qualification plan (described only; not executed)

This task did not provision any real-cloud resource beyond what S7/Track F already left in place, and did not execute this plan. If and when a real-cloud qualification of this specific PREPARE/rotation path is separately authorized, the smallest sufficient trial is:

1. **Topology:** reuse S7's own disposable-project pattern (a fresh, single-purpose GCP project; a single-node Spanner instance; a real GCS witness bucket) — never `emg-platform-staging`.
2. **Seed:** perform one real genesis (`bootstrap.ExecuteGenesis`, already real-cloud-qualified by Track F) to produce a genuine revision-1 `authority_head` row.
3. **Ordinary rotation, revision 1→2:** invoke `rotationexecute.ExecuteRotation` (via `cmd/recovery-rotate` or a disposable diagnostic wrapper, mirroring Track F's own pattern) against the real Spanner instance and real GCS bucket, with a real (or real-`localsigner`-substituted, scope-disclosed exactly as Track A/S7 already did) signer.
4. **Independent verification:** on a fresh connection, confirm the `authority_head` row now shows revision 2 with the expected `state_digest`, and independently verify the witness object via `recovery.VerifyPersistedCommitted`.
5. **Negative control:** repeat step 3 with a stale `ExpectedRevision` (still 1) and confirm refusal before any Commit is attempted (mirrors `TestMatrixB`, at the real-cloud tier).
6. **Cleanup:** delete the disposable Spanner instance/database; document (do not bypass) any Bucket-Lock retention lien exactly as S7's own `CLEANUP.md` did.

This plan is judged **not necessary to close ADR-044 §17 items 1/3** on its own: those items concern whether the *code path* exists and is qualified, and the emulator tier already qualifies the identical `completeRawCommit`/`ClassifyCommit`/`buildCommittedPayload` primitives against a real Cloud Spanner *emulator* server (a real gRPC/wire-protocol server, not a mock), while S7 already separately qualified those same primitives' behavior against real Cloud Spanner specifically for the process-death property. A full real-cloud repeat of the *rest* of the matrix (A–L, N) would be valuable additional confidence but is not, by itself, what stands between the current state and ADR-044 §17 items 1/3's closure — see P8.

## P8 — ADR-044 §17 closure determination

**`ADR044_SECTION17_ITEM1_RESULT` = COMPLETE (code-level; not `PRODUCTION_REALIZED`).** A production Spanner adapter capable of preparing and committing an ordinary rotation now exists (`rotationprepare` + `rotationcommit.CompleteRotationCommit` + the pre-existing `spannercommit` raw-Commit boundary), is emulator-qualified against the full adversarial matrix, and introduces no test-only or emulator-only code into the production import graph. It has not been run against real Cloud Spanner for the ordinary-rotation path specifically (P7); it has for genesis (Track F) and for the shared process-death primitives (S7).

**`ADR044_SECTION17_ITEM3_RESULT` = COMPLETE (code-level; not `PRODUCTION_REALIZED`).** A deployable binary (`cmd/recovery-rotate`) can now initiate a real, governed, non-genesis authority rotation end to end, composing only already-existing, already-reviewed production primitives (`spannercommit`, `gcswitness`, `signerrpc`, plus this task's new `rotationprepare`/`rotationexecute`). The disclosed, still-open gap is governance, not code: no dual-control/approval policy exists for ordinary rotations (see P5), and this task did not invent one.

**Neither result is, or is claimed to be, `PRODUCTION_REALIZED`.** Both remain gated, as they always were, by ADR-044 §17 item 9 (signing administrative independence) and by the separate, explicit production-approval decision ADR-044 §22 requires.
