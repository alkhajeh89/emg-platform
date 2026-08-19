# Evidence Manifest — ADR-044 Real-Cloud Wave 1, Track B (GCS Witness)

| File | Purpose | SHA-256 | Source | Sanitized? |
|---|---|---|---|---|
| `bucket_metadata_current.json` | Current bucket state (post-lock) | `1209ae26b2424afd687c9555ef490cf187772f11be98060b6b0239f4b65f3f7b` | `gcloud storage buckets describe` | No |
| `bucket_metadata_post_lock.json` | Raw `lockRetentionPolicy` REST response, `isLocked: true` | `a8ec431f135834bd2cb365cc4ce58a98bb5074f7a66714ac55507382074a015b` | `POST .../lockRetentionPolicy` | No |
| `witness_object_metadata_pre_lock.json` | Witness object metadata before retention was set | `e7776a0e03ef62176ee6e1050acaa410b34c759756e92373b59d5524323ca31d` | `gcloud storage objects describe`, pre-retention | No |
| `witness_object_metadata_post_lock.json` | Same object, after lock — byte-identity comparison (item 11) | `9f5858f179a462d60ea37f2933ed1c4a318ff087f73941909ae5e388dc225087` | `gcloud storage objects describe`, post-lock | No |
| `negative_operation_evidence.txt` | Exact status/reason text: delete, overwrite, retention-removal, retention-reduction (items 8–10) | `e5f6650c847aa507c5d94691c37846ad52c84405413d65955f7f8d806fe858e1` | Hand-extracted from `gcloud storage` command output | Yes — account email/local paths removed |
| `go_test_witness_qualification.log` | Full test output, items 1–7 | `5e80375411be04f2742a395211816e060b939cc325b7555f4163cffdf9672111` | `go test -tags realcloud_gcs -run TestRealCloudGCSWitnessQualification -v` | No |
| `go_test_store_ledger_composition.log` | Full test output, GCSStore/GCSLedger composition | `ecdaeea735d41be2741078e7c9c9f6ca6fb51a8b6400a6d6177ad6444b1bf18f` | `go test -tags realcloud_gcs -run TestRealCloudGCSStoreAndLedgerComposition -v` | No |

## Identity cross-check (pre-lock vs. post-lock, witness object)

| Property | Pre-lock | Post-lock | Match |
|---|---|---|---|
| Generation | `1787163852531766` | `1787163852531766` | ✅ |
| MD5 | `mEWTtL/yVY2cPc09hzb5eQ==` | `mEWTtL/yVY2cPc09hzb5eQ==` | ✅ |
| CRC32C | `SPjpdA==` | `SPjpdA==` | ✅ |
| Size | 51 bytes | 51 bytes | ✅ |

**No discrepancies.** Bytes, generation, and hashes are unchanged across the entire
retention-set → lock transition.

## What was deliberately excluded

`negative_operation_evidence.txt` is hand-extracted, not a raw `--log-http` capture —
raw `gcloud` output for the delete/overwrite/retention attempts includes the
authenticated account's email address in diagnostic text, exactly the reason the
ADR-043 destructive-qualification evidence package cites for the same exclusion. No
bearer token was ever written to disk; the two real-cloud Go tests hold their token
in-process only (`oauth2.StaticTokenSource`, sourced live from `gcloud auth
print-access-token`).

## B4 (ambiguous write / fault-proxy) — not qualified this run

Reported as `STILL_REQUIRED_FOR_S7` in the accompanying README, not fabricated. See
README §"B4" for the specific reason (TLS handshake size defeats the existing
fault-proxy's byte-count heuristic without new, unvalidated engineering against a live
endpoint).

## Cleanup status

Bucket Lock is irreversible. Earliest safe cleanup time: **2026-08-20T18:26:04.223Z**.
No delete/retention-bypass was attempted. See README §"Cleanup status" for full
detail.
