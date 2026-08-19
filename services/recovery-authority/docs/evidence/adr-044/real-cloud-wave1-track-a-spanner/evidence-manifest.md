# Evidence Manifest — ADR-044 Real-Cloud Wave 1, Track A (Spanner)

| File | Purpose | SHA-256 | Source | Sanitized? |
|---|---|---|---|---|
| `instance_metadata.json` | Disposable Spanner instance state (`emg-s7-prequal`) | `d5d957baf04db44fae48d31be4cdcc659d866b2415bdd6432a35f628e81720b2` | `gcloud spanner instances describe` | No |
| `database_metadata.json` | Disposable database state (`authority`) | `3ddb66969468864725c9860257ee644e7fe906e7c66e62ad870f786b1311ac33` | `gcloud spanner databases describe` | No |
| `database_ddl.sql` | Applied schema, confirmed identical (modulo formatting) to `scripts/emulator/schema.sql` | `d4c55207d67c5e32cafe45c55ccbc7463de72870805fc005678d48256a20aa7a` | `gcloud spanner databases ddl describe` | No |
| `commit_classification_evidence.json` | Per-subtest outcome/reason/gRPC-code/commit-timestamp from the real qualification test | `1886dd08871e31920b1cdb934c300b29865b2456295ae37dfec848a43cbf349c` | `TestRealCloudSpannerQualification` (`-tags realcloud_spanner`) | Yes — emitted directly by the test, no tokens/credentials |

## Cross-check against Track A findings

| Property | Value |
|---|---|
| Project | `emg-adr043-disposable-witness` |
| Instance | `emg-s7-prequal` (100 PU, regional-us-central1, STANDARD) |
| Database | `authority` (GOOGLE_STANDARD_SQL) |
| RealCommitSucceeds classification | `UNAMBIGUOUS_SUCCESS`, reason 2 (`ReasonSuccessfulResponse`) |
| DuplicateInsertFailsClosed classification | `AMBIGUOUS_COMMIT_OUTCOME`, reason 0 (`ReasonUnknown`) — never `UnambiguousSuccess` |
| DeadlineInterruption classification | `AMBIGUOUS_COMMIT_OUTCOME`, grpc code `Unknown` — never `UnambiguousSuccess` |
| `ClassifyCommit` call sites (repo-wide) | Exactly one (`rotationcommit/accepted_context.go:67`) |

## What was deliberately excluded

No raw `--log-http`/token capture was ever written to disk. Bearer tokens were held
only in-process (via `oauth2.StaticTokenSource`, sourced live from `gcloud auth
print-access-token` at test run time) and never logged, printed, or persisted.

## Cleanup

The `emg-s7-prequal` Spanner instance and `authority` database were deleted
immediately after this evidence was captured (`gcloud spanner databases delete` /
`gcloud spanner instances delete`, both confirmed with an empty
`gcloud spanner instances list` afterward). No standing Spanner resource remains from
Track A.
