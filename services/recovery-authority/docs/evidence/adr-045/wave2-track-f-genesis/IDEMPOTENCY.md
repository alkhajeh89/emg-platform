# Phase 7 — Idempotency / Rerun

The exact same, already-completed `GenesisRequest` (identical `environment_id`, `resource_incarnation_id`, `authority_epoch`, `operation_id`, freshly re-approved dual control bound to the identical resulting digest) was submitted a second time.

```
RESULT {"outcome":"ALREADY_COMPLETED"}
```

This exercises `bootstrap.ExecuteGenesis`'s `handleExistingWitness` path: the deterministic witness key already held content, which was independently re-verified (cryptographic signature check via `recovery.VerifyPersistedCommitted`, not merely "a byte string exists") before being reported as a successful, idempotent retry — never a second real commit.

## Proven from real provider-side state, not application logs

| Check | Before rerun | After rerun |
|---|---|---|
| `authority_head` row count | 1 | **1 (unchanged)** |
| `authority_transition_history` row count | 1 | **1 (unchanged)** |
| Witness object generation | `1787524248433694` | **`1787524248433694` (unchanged — no overwrite)** |

Zero second Spanner Commit, zero second genesis revision, zero conflicting witness replacement. No second signing operation occurred: the idempotent path verifies the existing signature cryptographically against the pinned public key rather than calling the live signer again.
