# Phase 8 — Forbidden Recovery Path Audit

Performed after the real-cloud trials, across the entire `services/recovery-authority` tree at `d8e2620` plus this task's own new test file.

| Search | Command | Result |
|---|---|---|
| Any Spanner read used to resolve/reclassify a Commit outcome | `grep -rn "ClassifyCommit\|TransitionOnCASOutcome" --include="*.go" internal/ \| grep -v _test` | Only the known, reviewed call sites (`accepted_context.go`, `genesis.go`, `epoch/state.go`, `spannercommit/commit.go` doc comment) — none reads Spanner to produce a classification |
| Any exported/reachable constructor for `acceptedRotationContext` outside `rotationcommit` | `grep -rln "acceptedRotationContext" --include="*.go" internal/ \| grep -v internal/authority/rotationcommit/` | Only doc-comment references in `bootstrap/genesis.go`, `signerrpc/signerrpc.go`, `gcswitness/boundary_test.go`, `bootstrap/boundary_test.go`, `bootstrap/attack_matrix_test.go`, `bootstrap/realcloud_spanner_test.go` — all *describing* the boundary, none constructing or reaching it |
| Any serialization of `acceptedRotationContext` | `grep -rn "acceptedRotationContext" internal/authority/rotationcommit/*.go \| grep -i "json\|marshal\|gob\|proto\|serializ"` | None found |
| Any change-stream/audit-log-based recovery mechanism | `grep -rln "ChangeStream\|change_stream\|AuditLog\|audit_log" --include="*.go" internal/authority/` | None found |
| Any `TransitionOnWitnessOutcome` call fed by something other than a same-process write result | `grep -rn "TransitionOnWitnessOutcome" --include="*.go" internal/ \| grep -v _test` | The single real call site (`bootstrap/genesis.go:216`) is fed directly by `createOutcome == gcswitness.CreateSuccess \|\| createOutcome == gcswitness.AlreadyExistsIdentical` — the same process's own witness-write attempt, never a read |
| `gcswitness` LIST capability | `grep -n "func.*List\|\.List(" internal/authority/gcswitness/gcswitness.go` | No `List` method exists anywhere in the package (already structurally enforced, re-confirmed) |
| Any function producing a signed `CommittedPayload` from Spanner-row data without a live `acceptedRotationContext` | `grep -rn "buildCommittedPayload(\|buildGenesisCommittedPayload(\|\.SignCommittedDigest(" --include="*.go" internal/ \| grep -v _test` then `grep -rln "NewCommittedPayloadV2\|WithSignature" --include="*.go" internal/ \| grep -v _test` | Only the two known, reviewed sites (`rotationcommit/genesis.go`, `rotationcommit/signer.go`); `signerrpc/server.go`'s `SignCommittedDigest` call is the signer's own RPC handler signing an authenticated caller's already-constructed digest — provenance discipline is enforced entirely on the caller side (`buildCommittedPayload`), which is the correct, already-reviewed design (the signer is a pure oracle, ADR-045) |

**No path violating ADR-044 was found. No P0/P1 audit finding.**
