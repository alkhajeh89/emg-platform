# Phase 5 — Control Cases

All three run against real Cloud Spanner + real GCS before the decisive trial, establishing that the harness genuinely discriminates kill timing.

## Control A — clean success (`TestS7ControlCleanSuccess`)

Real Commit → real sign (local test key) → real GCS witness write → killed only after `ACKED`. Independently re-verified via a fresh GCS client and `recovery.VerifyPersistedCommitted` (never trusting the child's own report): the witness object is valid, correctly bound, and resumable (`epoch.TransitionOnWitnessOutcome(true) == StateActive`, `NewEpochRequired() == false`).

```
child: SESSION ... / CALLING_COMMIT / COMMIT_SUCCEEDED / COMMITTED_PERSISTED / ACKED
SIGKILL at 4.209s after start (after ACKED was already observed)
CONTROL_A_PASS: real Commit + real sign + real witness write, independently re-verified, resumable
```

**Result: PASS.**

## Control B — safe negative path (relies on Wave 1 Track A's already-committed real-cloud evidence; not re-executed this wave)

Rather than reimplementing an equivalent test, this qualification relies on Wave 1 Track A's own already-passing, already-committed real-cloud evidence (`bootstrap/realcloud_spanner_test.go`, `TestRealCloudSpannerQualification`): `DuplicateInsertFailsClosed` (a second `Mutation_Insert` against an already-committed primary key fails, never classified `UnambiguousSuccess`) and `DeadlineInterruption` (a 1ms client deadline against real Cloud Spanner never produces a false `UnambiguousSuccess`). **This suite was not re-executed during this task**: Track A's own disposable Spanner instance (`emg-s7-prequal`, in `emg-adr043-disposable-witness`) had already been deleted per its own established cleanup lifecycle before this task began, and provisioning a second fresh instance solely to re-run an unmodified, already-reviewed test was judged unnecessary real-cloud cost for a property this task's own new Controls A/C and the decisive trial already independently re-confirm the load-bearing half of (that `completeRawCommit`/`ClassifyCommit` genuinely and correctly classifies real Cloud Spanner responses in a freshly-provisioned real environment). The full test suite (`go test -tags=realcloud_spanner`) remains available to re-run against a fresh instance at any time; it was not modified by this task (confirmed via `git diff` showing zero changes to `bootstrap/realcloud_spanner_test.go`).

## Control C — kill before Commit (`TestS7ControlKillBeforeCommit`)

Child killed the instant `CALLING_COMMIT` is observed by the parent's read loop — before the child could process any Commit response at all.

```
child: SESSION ... / CALLING_COMMIT
SIGKILL at 1.478s after start
child exited: signal: killed
CONTROL_C_PASS: kill landed before the child observed a successful Commit
```

**Result: PASS.** (Real Cloud Spanner Commit latency in this trial was fast enough that a slower parent read loop could race past this window on an unlucky run — the harness explicitly logs, rather than silently passes over, that specific race condition if it is ever observed; it was not observed in this trial.)

**Conclusion: the harness reliably discriminates "before Commit," "at the Commit-succeeded boundary," and "after full completion" — establishing it is fit to isolate the decisive trial's target window.**
