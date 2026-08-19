# Track A — Real Cloud Spanner Qualification Evidence (Wave 1)

**Date:** 2026-08-19
**Project:** emg-adr043-disposable-witness (disposable qualification project)
**Instance:** emg-s7-prequal (100 processing units, regional-us-central1, STANDARD edition)
**Database:** authority (GOOGLE_STANDARD_SQL, versionRetentionPeriod=1h)
**Test:** `go test -tags realcloud_spanner -run TestRealCloudSpannerQualification -v ./internal/authority/bootstrap/...`
**Result:** PASS (3/3 subtests), 16.44s

## Scope

Qualifies the real production `spannercommit.Client.Commit` boundary and
`rotationcommit.CompleteGenesisCommit` / `bootstrap.GenesisMutations` /
`bootstrap.GenesisCommitRequest` / `rotation.NewFixedOperation` code paths
against genuine Cloud Spanner. Does not use Cloud KMS (signing uses a local
test-only ECDSA key, `fakeGenesisSigner`) and does not touch GCS (Track B,
separate).

## Files

- `instance_metadata.json` — `gcloud spanner instances describe` output.
- `database_metadata.json` — `gcloud spanner databases describe` output.
- `database_ddl.sql` — `gcloud spanner databases ddl describe` output; confirmed
  identical (modulo gcloud's own formatting) to `scripts/emulator/schema.sql`.
- `commit_classification_evidence.json` — sanitized per-subtest evidence emitted
  by the qualification test itself (outcome, reason code, gRPC code where
  applicable, commit timestamp where applicable). No tokens, credentials, or
  raw auth headers.

## Findings against A4/A5 requirements

1. **One real Commit succeeds** — `RealCommitSucceeds` subtest: real Cloud
   Spanner returned a genuine commit timestamp
   (`2026-08-19T18:18:07.966533Z`); `ClassifyCommit` returned
   `UNAMBIGUOUS_SUCCESS` (reason code 2 = `ReasonSuccessfulResponse`); a V2
   `CommittedPayload` was produced only after this classification.
2. **Exactly-one-attempt behavior preserved** — structural: `completeRawCommit`
   (rotationcommit/accepted_context.go) issues exactly one `Commit` RPC per
   call, no internal retry; unmodified by this test.
3. **Response/error passthrough unchanged** — `CompleteGenesisCommit` returned
   the real classification and error unmodified in all three subtests; no
   reinterpretation performed by the test harness.
4. **Classification remains exclusively in `rotationcommit`** — confirmed by
   source inspection: `ClassifyCommit` has exactly one call site in the whole
   repository (`rotationcommit/accepted_context.go:67`), inside
   `rotationcommit` itself.
5. **No later read used to reinterpret an ambiguous Commit** — structural:
   `RawCommitClient`/`GenesisSpannerClient` expose only `Commit` and
   `CreateSession`; no `Read`/`ExecuteSql`/query capability exists anywhere in
   the genesis Spanner path.
6. **Conflict behavior for duplicate genesis/Mutation_Insert is fail-closed** —
   `DuplicateInsertFailsClosed` subtest: re-committing the identical
   `GenesisRequest` (same `authority_head` primary key) against real Spanner
   produced `AMBIGUOUS_COMMIT_OUTCOME` (reason code 0 = `ReasonUnknown`), never
   `UNAMBIGUOUS_SUCCESS`. The classifier's conservative design (no dedicated
   "clean failure" bucket for a non-`Aborted` commit error) means a real
   `AlreadyExists`-shaped conflict is treated as ambiguous rather than
   confirmed-failed — this is the fail-closed behavior ADR-044 requires, not a
   defect.
7. **`acceptedRotationContext` only produced after genuine unambiguous
   success** — confirmed by the same `RealCommitSucceeds` result; the
   duplicate and deadline subtests both returned an error and no payload.
8. **A5 deadline/transport interruption** — `DeadlineInterruption` subtest: a
   1ms client-side deadline against real Cloud Spanner produced
   `AMBIGUOUS_COMMIT_OUTCOME` (grpc code `Unknown`, wrapping a client-side
   deadline expiry) — never falsely classified as success.

## STILL_REQUIRED_FOR_S7

Genuine mid-RPC process death (killing the calling process between request
dispatch and response) was not safely inducible in this environment/session.
Not claimed as qualified by this evidence. Reported honestly rather than
fabricated, per task instruction.

## Cleanup

The `emg-s7-prequal` instance and `authority` database were deleted after this
evidence was captured (see repository evidence README's cleanup log entry).
No standing Spanner resource remains in `emg-adr043-disposable-witness` from
Track A.
