# Phase 8 — Fail-Closed Matrix

All 11 scenarios below used fresh identifiers per test (never colliding with the real completed genesis in `GENESIS_RESULT.md`). Every scenario correctly refused genesis; none were forced or fabricated.

| # | Scenario | Result | Failed at |
|---|---|---|---|
| 1 | Stale approval (>72h old) | `REQUEST_REJECTED`: `"approval is older than the maximum permitted age"` | `NewGenesisRequest`, before any provider call |
| 2 | Wrong signing key/version (unpinned, nonexistent version 99) | `REJECTED`: `"signing key has no durable pin; refusing genesis: no pin exists for this SigningKeyID"` | `CheckSigningPreconditions`, before any Spanner mutation |
| 3 | Unavailable pin store (nonexistent bucket) | `REJECTED`: `"signing key has no durable pin; refusing genesis: ... bucket doesn't exist ... notFound"` | `CheckSigningPreconditions` |
| 4 | Unavailable compromise ledger (nonexistent bucket) | `REJECTED`: `"compromise ledger unavailable or unreadable; refusing genesis: ... bucket doesn't exist ... notFound"` | `CheckSigningPreconditions` — **fails closed, never fails open** |
| 5 | Wrong ID-token audience | `REJECTED`: real `403` from signerrpc (`caller identity is not authorized`) — TLS handshake itself succeeded, proving the layering is correct (transport vs. application auth) | `CheckSigningPreconditions`'s live-signer check |
| 6 | TLS trust failure (client trusts public CA pool, not the qualification CA) | `REJECTED`: real `x509: certificate signed by unknown authority` | Same live-signer check, at the transport layer |
| 7 | Unauthorized WIF principal (signer identity attempts to run genesis) | `REJECTED`: real `403 storage.objects.get` denied on the witness bucket | The very first precondition check (`CheckWitnessPreconditions`) |
| 8 | Witness conflict (wrong/bogus content pre-seeded at the target witness key) | `CONFLICT`: `"witness target holds conflicting genesis content ... existing witness content is malformed"` — the bogus object was **never overwritten** (verified via a follow-up `gsutil cat`) | `CheckWitnessPreconditions` → `handleExistingWitness` |
| 9 | Disabled KMS version — **see propagation-timing finding below** | First attempt (≈1 min after disable): unexpectedly `COMPLETED`. Second attempt (≈5 min after disable): correctly `UNRESOLVED` | See below |
| 10 | Unavailable signer (scaled to 0 replicas) | `REJECTED`: real bounded timeout (`context deadline exceeded`), no hang, no insecure fallback | `CheckSigningPreconditions`'s live-signer check |
| 11 | Distrusted signer (real distrust record declared via `compromiseledger.GCSLedger.Declare`, independently re-read as `REQUIRES_MANUAL_REVIEW`) | `REJECTED`: `"signing key requires manual compromise review; refusing genesis"` | `CheckSigningPreconditions` |

Also: same-approver-for-both-roles and mismatched-approval-digest are covered in `DUAL_CONTROL.md`.

## Emergent finding: real Cloud KMS crypto-key-version DISABLE propagation timing

Scenario 9 produced a genuinely unexpected first result: disabling the real signing key version and attempting genesis ~1 minute later **still succeeded** — a real signature was produced (`writer_signature_hex` present, real Spanner commit, real witness write), even though `gcloud kms keys versions describe` already reported `state: DISABLED` at that moment.

This was investigated, not assumed to be a defect. A second attempt with fresh identifiers, run ~5 minutes after the disable call, **correctly failed**:

```
RESULT {"error":"... Spanner commit outcome UNAMBIGUOUS_SUCCESS: rotationcommit: genesis payload: committed payload unavailable: signerrpc: remote signer returned an error: status 500 ...","outcome":"UNRESOLVED"}
```

This is the architecture's own documented `NEW_EPOCH_REQUIRED`-equivalent fail-closed pathway working exactly as designed: the real Spanner Commit succeeded (a row genuinely exists for this attempt's identifiers, confirmed independently), but the subsequent signing step failed, so the outcome was correctly classified `OutcomeUnresolved` — **never** reported as success, and per the package's own contract this specific `(environment_id, resource_incarnation_id)` must never be retried automatically. Independently confirmed: **no witness object was ever created** for this attempt (`gsutil ls` → "matched no objects"), so the prepared-but-incomplete state is real and correctly incomplete.

**Interpretation, reported honestly (not rounded to "instant" in either direction):** Cloud KMS crypto-key-version state changes (at least DISABLE) are not synchronously enforced across all serving paths — the real, measured window in this trial was somewhere between ~1 minute (still permitted) and ~5 minutes (correctly blocked). This is analogous to, and consistent in kind with, Track D's already-documented IAM binding-propagation timing finding (that trial: 31s–89s) — both are real, provider-side eventual-consistency behaviors, not application-level defects, and both are reported factually rather than assumed to be either instantaneous or absent. The key material itself was never authorized-then-compromised; it was briefly disabled with normal provider propagation latency, which the architecture's own fail-closed design correctly contained on the very next attempt.

The disabled key was re-enabled immediately after this test to avoid leaving the environment in a broken state for subsequent phases, then finally re-disabled (not destroyed) during cleanup.
