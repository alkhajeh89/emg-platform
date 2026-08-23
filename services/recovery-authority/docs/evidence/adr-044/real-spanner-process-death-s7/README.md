# S7 — Real Cloud Spanner Process-Death Qualification

**Date:** 2026-08-23
**Authoritative start commit:** `d8e2620cea653cf36105dbea1eb16a8fab219470`
**S7 definition, verbatim source:** `services/recovery-authority/docs/runbooks/RECOVERY_AUTHORITY_PRODUCTION_RECOVERY_RUNBOOK.md` line 24, citing ADR-044 §17 item 7: *"Real-Spanner process-loss/crash qualification (currently only emulator-tested; see §9)."* ADR-044 §9 states the precise requirement: qualify genuine process loss (crash/restart/replacement) after a `Commit` classified `UnambiguousSuccess` but before the same-operation `COMMITTED` witness write completes, proving the epoch lands in the governed frozen/unresolved state with no live `acceptedRotationContext` and no reconstruction path.

**Scope: this qualification only.** Does not authorize production deployment, does not resolve the separate GCS ambiguous-write gap, does not establish production administrative independence, and does not modify ADR-044/ADR-045.

## Baseline correction carried forward from the S7 readiness review

The readiness review that authorized this task identified that prior sessions' ADR zero-diff checks referenced a nonexistent `docs/adr/` path; the real files live at `docs/architecture/EMG_ADR-044_*.md` / `EMG_ADR-045_*.md`. This task uses the correct paths throughout (see `FULL_VALIDATION.md`).

## Design: extending an already-reviewed pattern, not inventing a new one

`internal/authority/rotationcommit/emulator_processkill_test.go` already implements a T7/T8/T10 process-kill matrix against the Cloud Spanner **emulator**, using the exact technique this qualification needed: re-executing the same test binary as a subprocess (`TestMain` dispatch via an environment variable), because `completeRawCommit`, `acceptedRotationContext`, and `buildCommittedPayload` are unexported **by design** — the security boundary this qualification exists to prove is real, not an inconvenience to route around. `services/recovery-authority/internal/authority/bootstrap/realcloud_spanner_test.go` (Wave 1 Track A) already qualified real Cloud Spanner Commit behavior and ends with an explicit, first-party admission: *"STILL_REQUIRED_FOR_S7: genuine mid-RPC process death ... was not safely inducible in this environment/session and is not claimed as qualified by this run."*

This qualification is a new file, `internal/authority/rotationcommit/realcloud_spanner_processdeath_test.go`, build-tag-gated `realcloud_spanner_processdeath` (never runs in `go test ./...`, CI, or any default invocation), that extends the emulator T7/T8 pattern to real Cloud Spanner: same subprocess-kill technique, same decision logic, only the dial target (real Cloud Spanner via `spannercommit.Dial` + OAuth2 token, wrapped by the existing `spanneradapter.Client` helper) and the witness backend (real, Bucket-Locked GCS) differ.

**No production code was modified to create this test seam.** `rotationcommit`, `bootstrap`, `epoch`, `gcswitness`, and `protocol` are byte-for-byte unchanged. The crash barrier is a plain `time.Sleep` inside a qualification-only helper-mode branch of a `_test.go` file, gated behind a build tag that is never active in any normal build.

**Signing:** a local, test-only ECDSA signer (`conformance/localsigner`), not real Cloud KMS — the identical scoping decision Track A's own real-cloud test already made and documented, because the property under qualification (Spanner-Commit/witness process loss) is orthogonal to which `Signer` implementation is used, and the real KMS/TLS/WIF signing boundary was already exhaustively qualified against real infrastructure in Wave 2 Tracks C/D/E/F.

## Topology (fresh, disposable, distinct from `emg-platform-staging`)

Per explicit instruction, this qualification does **not** reuse `emg-platform-staging`.

| Resource | Identity |
|---|---|
| Project | `emg-ra-s7-spanner-3400f9e2` (fresh, disposable) |
| Spanner instance | `s7-processdeath` (100 PU, `regional-me-central1`) |
| Database | `authority`, real DDL from `scripts/emulator/schema.sql` (byte-identical to the landed schema) |
| Witness bucket | `emg-s7-processdeath-witness` (versioned, Bucket Lock **locked** at 1 day before any trial) |
| Credentials | The operator's own `gcloud auth print-access-token` session (identical technique to `realcloud_spanner_test.go`) — no service-account key, no WIF, no Kubernetes topology (none of the S7 code path requires them; Phase 4 explicitly calls for the minimum necessary topology) |

## Contents

- `CRASH_WINDOW.md` — Phase 1: exact functions/files/lines defining the target window
- `CONTROLS.md` — Phase 5: Control A/B/C results
- `DECISIVE_TRIAL.md` — Phase 6/7: the central real process-death trial and post-restart recovery proof
- `FORBIDDEN_RECOVERY_AUDIT.md` — Phase 8
- `ATTACK_MATRIX.md` — Phase 12
- `PROVIDER_FACT_CHECK.md` — Phase 13
- `AMBIGUITY_DISTINCTION.md` — Phase 11
- `CLEANUP.md` — Phase 15
- `LIMITATIONS.md`
- `decisive_trial_evidence.json` — raw, sanitized evidence from the decisive trial
- `SHA256SUMS.txt`

## Summary

**S7 is qualified.** A real Commit against real Cloud Spanner was classified `UnambiguousSuccess`; the process was then hard-killed (`SIGKILL`) before it ever called the signer or attempted a witness write; ground truth independently confirmed the row was genuinely, unambiguously committed (revision 1) — and this fact was never consulted in the recovery decision; no witness object was ever created; the governed decision, computed from the zero value alone, correctly evaluated to `StateEpochTerminated` with `NewEpochRequired() == true` and every authority-dependent action denied; three independent, genuinely fresh restart processes (0s/2s/5s apart) all converged to the identical fail-closed decision, with no healing across restarts.
