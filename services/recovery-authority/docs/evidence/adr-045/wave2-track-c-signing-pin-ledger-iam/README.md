# Wave 2 Track C — Real-Cloud KMS / Pin-Store / Compromise-Ledger / IAM Qualification

**Date:** 2026-08-21 – 2026-08-22
**Scope:** disposable qualification of ADR-045 S3 production adapters (`kmssigner`, `keypinning.GCSStore`/`CaptureFromKMS`, `compromiseledger.GCSLedger`, `kmsverifier`) and the S4 IAM manifest against genuine Cloud KMS, genuine GCS, and genuine (narrowly-scoped, disposable, impersonated) IAM principals.
**Explicitly out of scope, not started:** Track D (WIF), Track E (Kubernetes), end-to-end genesis, S7.
**Does not prove:** ADR-045 §15A production administrative independence — that requires a genuinely separate Cloud Identity/Workspace domain, not disposable projects under one organization.

## Resources used

| Resource | Identity | Purpose |
|---|---|---|
| Signing project | `emg-ra-signing-qual-db77c759` | disposable, holds the KMS key + pin bucket |
| Ledger project | `emg-ra-ledger-qual-922b972d` | disposable, administratively distinct third project, holds the compromise-ledger bucket |
| KMS key version | `.../keyRings/ra-signing-qual-ring/cryptoKeys/ra-signing-qual-key/cryptoKeyVersions/1` | `EC_SIGN_P256_SHA256`, `SOFTWARE`, `ENABLED` |
| Pin bucket | `emg-ra-signing-qual-pins-b74565b9` | disposable, not Bucket-Locked (create-if-absent already provides the required immutability; see README §"Bucket Lock decision") |
| Ledger bucket | `emg-ra-ledger-qual-1978fd61` | disposable, not Bucket-Locked, same reasoning |
| Qualification service accounts | `ra-signer-qual@…`, `ra-pincapture-qual@…`, `ra-ledgerwriter-qual@…`, `ra-verifier-qual@…` | narrowly-scoped, impersonated by the human operator (`roles/iam.serviceAccountTokenCreator`) purely as test infrastructure — never a runtime credential |
| Custom IAM roles | `raQualPinCaptureWriter`, `raQualLedgerWriter`, `raQualVerifierReader` (×2 projects) | see `role_*.json`; exact permissions documented below |

## Two real defects found and fixed (the point of qualification)

### Defect 1 — compromise-ledger timestamp precision (P1, correctness/availability, fails closed)

- **Discovery:** the very first real-cloud `GCSLedger.Declare` idempotent-retry test failed against real GCS with a spurious `ErrDistrustConflict`.
- **Root cause:** `gcsDistrustRecord`/`fileRecord`'s wire format stored `EffectiveTime`/`RecordedAt` as whole-second Unix integers (`.Unix()`); the idempotency/conflict comparison then compared the caller's full-precision, freshly-supplied `time.Time` against a round-tripped, second-truncated value — any `EffectiveTime` with a non-zero fractional second could never match on retry. The same truncation also affected `EvaluateStatus`'s comparison against a record's genuinely sub-second-precision Spanner `commit_timestamp`, shifting the effective distrust boundary earlier by up to one second.
- **Fix:** both `GCSLedger` and `FileLedger` now encode `EffectiveTime`/`RecordedAt` as `time.RFC3339Nano` strings (matching `protocol.MarshalCommittedPayloadJSON`'s own convention for `commit_timestamp`), UTC-normalized on encode, with decode errors failing closed (never silently reinterpreted as the zero time). No production deployment of this code existed, so this is a clean wire-format correction, not a migration.
- **Local regression:** `internal/authority/compromiseledger/precision_test.go` (`TestAttackA`–`TestAttackG`, `TestDifferentSecondsConflicts`, `TestRoundTripPreservesNanosecondPrecision`) — see local test run in Phase 8/14 validation logs.
- **Real-cloud regression:** `go_test_ledger_p1_regression_retest.log`, `go_test_ledger_verifier_integration_retest.log` — nanosecond-precision idempotent retry, nanosecond-different conflict, and exact round-trip all confirmed against real GCS.

### Defect 2 — `gcswitness` bucket-vs-object-404 collapse (P0, fail-open security defect)

- **Discovery:** a real-cloud test pointing `GCSLedger.Status` at a nonexistent bucket returned `(StatusNotDistrusted, nil)` instead of an error.
- **Root cause:** `cloud.google.com/go/storage` returns the identical `storage.ErrObjectNotExist` sentinel (HTTP 404) from an object-resource call whether the specific object is absent or the containing bucket does not exist at all — confirmed empirically against both real GCS and `fake-gcs-server`. `gcswitness.Adapter.Exists`/`ReadExact` classified solely on this sentinel, so a missing/misconfigured/deleted bucket was indistinguishable from "object not yet created."
- **Severity:** direct violation of ADR-045 §7's explicit "Fail-closed scope" clause ("Unavailability of the compromise record... SHALL fail closed — an inability to rule out an undetected compromise is itself a verification failure") and §18 qualification requirement 15. A misconfigured/deleted compromise-ledger bucket would have caused every subject to silently report `StatusNotDistrusted`.
- **Fix:** `gcswitness.Adapter` gained `confirmBucketExists` (an independent `BucketHandle.Attrs` call, the SDK's only resource-level way to distinguish `ErrBucketNotExist` from object absence), invoked whenever `Exists`/`ReadExact` observes `ErrObjectNotExist`. `CreateExactIfAbsent` already failed closed on a missing bucket (404 was already in its `isHardFailure` list) — verified, not changed.
- **Side effect discovered and corrected:** the fix requires `storage.buckets.get`, a permission no existing IAM-manifest principal declared. Confirmed empirically (a correctly-scoped read-only principal received a spurious "bucket unavailable" error on the ordinary case of a genuinely absent object) and corrected in `internal/authority/iam/manifest.json` for every principal that calls `gcswitness.Exists`/`ReadExact` (`recovery-authority-runtime`, `recovery-pin-capture`, `compromise-ledger-writer`, `recovery-verification-read`, `recovery-bootstrap-deployment`), with the reasoning recorded in each principal's `notes` field.
- **Local regression:** `gcswitness/bucket_availability_test.go` (items A–J, plus a dynamic "bucket removed mid-lifecycle" test), `gcswitness/boundary_test.go` additions (no LIST usage, no error-message string parsing), caller-level tests in `compromiseledger/bucket_availability_test.go`, `keypinning/bucket_availability_test.go`, `bootstrap/bucket_availability_test.go`.
- **Real-cloud regression:** `go_test_ledger_p0_regression_retest.log`, `go_test_pin_bucket_availability.log`, `go_test_witness_bucket_availability.log`, `go_test_ledger_verifier_integration_item7.log` (full sign→pin→ledger→verify pipeline correctly fails closed when the ledger bucket is unavailable, even for a signature that would otherwise legitimately verify).

## Bucket Lock decision

Neither the pin bucket nor the ledger bucket was Bucket-Locked for this qualification. `CreateExactIfAbsent`'s GCS precondition (`ifGenerationMatch=0`) already provides the "never silently replace" property independent of Bucket Lock, and Wave 1 (Track B) already qualified Bucket Lock's own lifecycle mechanics fully against a real bucket — re-locking here would be redundant re-qualification of an already-proven mechanism, not new coverage, while adding irreversible resource commitment.

## Real KMS signer qualification (12 items, Phase 5)

See `go_test_kms_full_phase5.log`, `key_metadata.json`, `keyring_metadata.json`, `keyversion_metadata.json`. All 12 items proven: `ActiveKeyID` resolution, exact-version signing, confirming-key-ID match, real digest signs, real signature verifies, wrong digest fails, wrong key fails, unsupported algorithm fails closed (structural), disabled-version behavior (empirically characterized — see `PROVIDER_FACT_CHECK.md`), no private-key exposure (structural), no alternate-key fallback (structural), no discovery/listing capability (structural, `TestNoListMethodUsage`-equivalent).

## Real pin-store qualification (Phase 6)

See `go_test_pin_qualification.log`. `CaptureFromKMS` + `GCSStore.Pin`/`.Get` round-tripped against real Cloud KMS + real GCS: create-if-absent, idempotent duplicate, conflicting duplicate fail-closed (`ErrPinConflict`), no overwrite, fingerprint independently recomputed on read.

## Real compromise-ledger qualification (Phase 8, re-run post-fix)

See `go_test_ledger_p0_regression_retest.log`, `go_test_ledger_verifier_integration_item7.log`. First declaration, idempotent duplicate (nanosecond-precise), conflicting EffectiveTime/RecordedBy fail closed, exact retrieval, missing-record correctness, unavailable-provider fail-closed, and the full real sign→pin→ledger→verify pipeline (pre-distrust signature verifies; identical post-distrust signature routed to manual review; ledger-unavailable prevents verification success even for an otherwise-valid signature).

## Real IAM allow/deny matrix (Phase 9)

See `go_test_iam_qualification_v2.log` (the corrected, passing run — `go_test_iam_qualification.log` is preserved as the honest record of the first attempt, which surfaced the `storage.buckets.get` gap described above).

| Principal | Role(s) | Allowed (proven) | Denied (proven) |
|---|---|---|---|
| Signer | `roles/cloudkms.signer` on the CryptoKey | `AsymmetricSign` | `GetPublicKey`, `UpdateCryptoKeyVersion` (key admin), pin-store write, ledger write, `SetIamPolicy` on the CryptoKey |
| Pin-capture | `roles/cloudkms.viewer` + `roles/cloudkms.publicKeyViewer` on the CryptoKey; `raQualPinCaptureWriter` on the pin bucket | `GetCryptoKeyVersion`+`GetPublicKey` (via `CaptureFromKMS`), pin create | `AsymmetricSign`, object delete, bucket IAM-policy read, ledger write (no cross-project binding) |
| Ledger-writer | `raQualLedgerWriter` on the ledger bucket | `Declare` | `AsymmetricSign` (denied; KMS API not even enabled in this project, an even stronger deny), pin-store write (no cross-project binding), prior-record delete, bucket IAM-policy read |
| Verifier | `raQualVerifierReader` on both buckets (cross-project) | required reads (`Exists`) on both buckets | writes on both buckets, `AsymmetricSign` |

**Custom role exact permissions** (see `role_*.json`): `raQualPinCaptureWriter`/`raQualLedgerWriter` = `storage.objects.create`, `storage.objects.get`, `storage.buckets.get` — nothing else. `raQualVerifierReader` = `storage.objects.get`, `storage.buckets.get` — nothing else (no `list`, no `create`, no `getIamPolicy`).

**Confirmed absent for every qualification principal** (checked directly against each project's IAM policy — see `signing_project_metadata.json`/`ledger_project_metadata.json` context and the bucket/key IAM policy files): no `roles/owner`, `roles/editor`, `roles/storage.admin`, `roles/cloudkms.admin`, no `setIamPolicy` capability beyond what was explicitly tested-and-denied, no `iam.serviceAccountKeys.create`, no `iam.serviceAccounts.actAs`/`getAccessToken`/`signBlob`/`signJwt`, no project/folder/org administration. None of the four qualification service accounts holds any project-level IAM binding at all — every capability is bound at the exact bucket/key resource level shown above.

## Attack matrix

The pre-existing `kmsverifier` adversarial suite (`TestMatrix_A` through `TestMatrix_Y`, 19 tests — attacker-owned keys, foreign lineage, key-ID tampering, unknown keys, routine rotation, disablement-with-pin, missing pin, substituted pin, wrong-key signatures, no try-all-keys fallback, pre/post-compromise timing, ledger-unavailable, KMS-outage-does-not-break-history, superseded lineage, foreign-payload lineage, and the three-gate independence proofs) all pass unmodified (see the top of `go_test_iam_qualification_v2.log`'s companion run). This session adds real-cloud coverage for exactly the attacks that only a live provider can prove: signing-admin/pin-capture/ledger-writer cross-capability denial (IAM matrix above), real disabled-key signing behavior (Phase 5), and the two defects' own self-falsification attacks (`TestAttackA`–`TestAttackH` in `precision_test.go`; `bucket_availability_test.go`'s items A–J).

## Provider fact-check

See `PROVIDER_FACT_CHECK.md`.

## Cleanup status

Performed after evidence capture, in this order:

1. KMS qualification key version **disabled** (`DISABLED`, never destroyed) — see `keyversion_final_disabled_state.json`.
2. Pin bucket (`emg-ra-signing-qual-pins-b74565b9`) and ledger bucket (`emg-ra-ledger-qual-1978fd61`) — neither was Bucket-Locked, so both were deleted along with their contents (`gcloud storage rm -r`); confirmed gone (`404` on describe).
3. Both disposable projects (`emg-ra-signing-qual-db77c759`, `emg-ra-ledger-qual-922b972d`) deleted via `gcloud projects delete` — this removes the remaining service accounts, custom IAM roles, and IAM bindings as part of standard project teardown. Both confirmed `DELETE_REQUESTED` (see `signing_project_deleted_state.json`, `ledger_project_deleted_state.json`) — GCP's standard ~30-day recoverable deletion window, not an irreversible purge; `gcloud projects undelete` remains available during that window if ever needed, though no further use of these disposable projects is anticipated.
4. `emg-platform-staging` was never referenced or touched at any point in Track C.

No retention/Bucket-Lock protection existed on either bucket, so no cleanup delay was required and none was bypassed.
