# Phase 6/7 — The Decisive Real Process-Death Trial

`TestS7DecisiveProcessDeathTrial`, run against real Cloud Spanner (`emg-ra-s7-spanner-3400f9e2`) and real GCS (`emg-s7-processdeath-witness`).

## Sequence executed

1. Fresh identifiers minted (`environment=s7-processdeath-qual`, fresh UUIDv7-shaped epoch/resource/operation).
2. Child subprocess spawned (real, separate OS process — the same test binary, re-executed via `EMG_S7_HELPER_MODE=decisive`).
3. Child: `CreateSession` → `BeginReadWrite` → `ReadAuthorityHead` → builds real `spannerpb.CommitRequest` → prints `CALLING_COMMIT` → calls the real, unexported `completeRawCommit` against real Cloud Spanner.
4. Real `CommitResponse` received; `ClassifyCommit` returns `UnambiguousSuccess`; child prints `COMMIT_SUCCEEDED`.
5. **Parent hard-kills the child (`SIGKILL`) the instant `COMMIT_SUCCEEDED` is observed** — 1.058s after the child started, before it ever calls the signer or attempts any witness activity.
6. Parent confirms the child is dead (`cmd.Wait()` returns `signal: killed`).
7. Parent independently re-verifies, via a **fresh** Spanner connection: the row genuinely exists at revision 1, with a real server-assigned commit timestamp — **ground truth, logged, never consulted in the decision below.**
8. Parent independently re-verifies, via a **fresh** GCS client: no witness object exists at the deterministic key.
9. **The recovery decision** is computed from `var state epoch.State` (the zero value, `StateUnresolvablePreparedOperation`) → `epoch.Terminate(state)` → `StateEpochTerminated`, `NewEpochRequired() == true`, every authority-dependent predicate (`RecoveryAllowed`, `RotationAllowed`, `FenceReleaseAllowed`, `PostgreSQLReconciliationAllowed`) `== false`.
10. Three independent, genuinely fresh **restart** processes are then spawned (0s, 2s, 5s apart — `EMG_S7_HELPER_MODE=recovery-attempt`), each with zero shared memory with the killed child or each other. Each: reads real Spanner (ground truth, logged only), checks real GCS (ground truth, logged only), and independently computes and prints the identical decision.

## Real output (sanitized; full raw evidence in `decisive_trial_evidence.json`)

```
child: CALLING_COMMIT
child: COMMIT_SUCCEEDED
SIGKILL pid=87850 at 1.058s after start
child exited: signal: killed
ground truth CONFIRMS backend commit == SUCCESS (revision 1) -- decision computed WITHOUT consulting this fact
DECISIVE_TRIAL_PASS: decision=EPOCH_TERMINATED (NEW_EPOCH_REQUIRED=true)

restart 0: GROUND_TRUTH_ROW_FOUND=true revision=1 / GROUND_TRUTH_WITNESS_EXISTS=false
           DECISION state=EPOCH_TERMINATED new_epoch_required=true recovery_allowed=false
restart 1: identical
restart 2: identical
RESTART_MATRIX_PASS: 3 independent fresh processes, with delays, all converged to the identical fail-closed decision
```

## Explicit falsification attempts (Phase 7's required list)

Every restart process's output includes the line:

```
FALSIFICATION_ATTEMPT: a matching committed-looking Spanner row exists with no witness -- if this process
treated that as sufficient acceptance provenance, it would wrongly resume; it does not, per the DECISION
line above, which is computed without consulting `found`.
```

Supplying, or having available, a matching `operation_id`, matching `revision`, matching `commit_timestamp`, or a matching `authority_head`/`authority_transition_history` row did **not** substitute for `acceptedRotationContext` at any point — the recovery-attempt process's `DECISION` line is a pure function of the zero value, and its code never branches on the ground-truth facts it separately logs.

## Postconditions proven

1. Spanner contains the successful transition (real row, revision 1, real commit timestamp) — confirmed by a fresh read.
2. No same-operation `COMMITTED` witness exists — confirmed by a fresh GCS `Exists` call.
3. No `acceptedRotationContext` exists or can be reconstructed — structurally guaranteed (unexported type, unexported constructor, never serialized anywhere in this codebase — confirmed in `FORBIDDEN_RECOVERY_AUDIT.md`) and empirically demonstrated (three fresh processes, none of which ever had one).
4. A later Spanner read was not used to reclassify or recover the original Commit — the decision variable's computation never references the read's result.
5. Matching Spanner bytes/row/history are insufficient to establish acceptance provenance — explicitly demonstrated by the `FALSIFICATION_ATTEMPT` line.
6. No fabricated `COMMITTED` witness was ever produced.
7. The epoch remains in the documented unresolved/terminated condition (`EPOCH_TERMINATED`).
8. `NewEpochRequired()` evaluates `true`.
9. The only governed continuation is a new epoch with fresh identifiers — never a retry of this exact `(environment_id, resource_incarnation_id, authority_epoch, operation_id)` tuple.
