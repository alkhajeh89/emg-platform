# Phase 1 — Exact Failure Window

Traced directly from the real, unmodified production code (line references as of `d8e2620`):

| Step | Location | What happens |
|---|---|---|
| A. Raw Commit request sent | `internal/authority/rotationcommit/accepted_context.go:66` | `response, commitErr := client.Commit(ctx, request)` inside `completeRawCommit` |
| B. Provider returns a valid `CommitResponse` | Same line; classified at `classifier.go:64-78` (`ClassifyCommit`) | A structurally valid, strictly-positive `CommitTimestamp` with no error |
| C. `ClassifyCommit` returns `UnambiguousSuccess` | `accepted_context.go:67` | `classification := ClassifyCommit(true, response, commitErr, RegularSession)` |
| D. `acceptedRotationContext` exists only in the current process | `accepted_context.go:71-77` | `accepted := newAcceptedRotationContext(...)`, returned to the caller — an unexported type, unexported constructor, reachable only inside this same function |
| — return to orchestrator | `genesis.go:36` (`CompleteGenesisCommit`) | `accepted, classification, err := completeRawCommit(...)` — the earliest point at which a live `acceptedRotationContext` exists in the calling orchestrator's memory |
| — signing (still same process) | `genesis.go:40` → `genesis.go:51-98` (`buildGenesisCommittedPayload`) | Calls the real `Signer.ActiveKeyID`/`SignCommittedDigest` to produce a validly-signed `protocol.CommittedPayload` |
| E. Same-operation `COMMITTED` witness durably persisted | `bootstrap/genesis.go:214` | `deps.Witness.CreateExactIfAbsent(ctx, witnessKey, wireBytes)` — outside `rotationcommit` entirely, in the `bootstrap` orchestrator |
| F. Process killed | — | Target: any point in [D, E) |

**Target window selected for the decisive trial: immediately after C/D (right after `completeRawCommit` returns `UnambiguousSuccess`), before the signer is ever called and before any witness activity begins.** This is the earliest, purest instance of the required window — it isolates the process-death property from the signing/witness machinery entirely, and is the exact analogue of the already-reviewed emulator-tier "T8" scenario in `emulator_processkill_test.go`.

A wider point later in the same window (after signing, before the witness write — proving loss of an already-produced real signature) was considered but not separately trialed: `buildGenesisCommittedPayload`'s own internal call sequence (`ActiveKeyID` → construct digest → `SignCommittedDigest`) is itself a single, short, uninterrupted synchronous call chain with no additional externally-observable sentinel point between "Commit succeeded" and "signing complete" without modifying production code to add one — which Phase 2 explicitly prohibits. The T8-equivalent point (immediately post-Commit) already fully proves the load-bearing property (`acceptedRotationContext` cannot survive a process boundary, regardless of how much or how little was done with it before death) and is the identical point the already-accepted emulator-tier test already qualifies this exact way.

**It is not sufficient to, and this qualification does not:** return an artificial error; cancel a context; simulate a crash with an in-memory fake; kill before the provider Commit finishes (that is Control C, tested separately, see `CONTROLS.md`); or kill after the witness already exists (that is Control A). The decisive trial kills a real OS process, with `SIGKILL`, after a real, positive-timestamp `CommitResponse` from real Cloud Spanner.
