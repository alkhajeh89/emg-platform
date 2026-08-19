# Track B — Real GCS Witness Qualification Evidence (Wave 1)

**Date:** 2026-08-19
**Project:** emg-adr043-disposable-witness (disposable qualification project)
**Bucket:** emg-s7-prequal-witness-0a880ebc (region US-CENTRAL1, uniform bucket-level
access, public access prevention enforced, labels `disposable=true,
purpose=adr044-s7-prequal`)
**NOT reused:** `emg-adr043-blockera-destructive-08657059` (the ADR-043 destructive
qualification bucket) was never written to or reused by this task -- confirmed by
`gcloud storage buckets list` precheck before creation.

## Scope

Qualifies the real production `gcswitness.Adapter` (create-if-absent / ReadExact /
Exists) and, composed directly over the same real Adapter, `keypinning.GCSStore` and
`compromiseledger.GCSLedger` -- all unmodified production code -- against a genuine,
fresh, Bucket-Locked GCS bucket. Also independently verifies (via `gcloud storage` /
raw REST, since `gcswitness` deliberately exposes no Delete/Update/Retention method)
that real Bucket Lock retention enforcement behaves as ADR-044's immutability model
requires.

## Files

- `bucket_metadata_current.json` — current `gcloud storage buckets describe` output.
- `bucket_metadata_post_lock.json` — raw REST `lockRetentionPolicy` response
  (`isLocked: true`).
- `witness_object_metadata_pre_lock.json` / `witness_object_metadata_post_lock.json` —
  the same witness object's metadata immediately before retention was set and after
  the lock, for byte-identity comparison (item 11).
- `negative_operation_evidence.txt` — exact HTTP status/reason text for delete,
  overwrite, retention-removal, and retention-reduction attempts (items 8–10), and the
  Bucket Lock REST call itself.
- `go_test_witness_qualification.log` — full `go test -tags realcloud_gcs -run
  TestRealCloudGCSWitnessQualification -v` output against the real bucket (items 1–7).
- `go_test_store_ledger_composition.log` — full `go test -tags realcloud_gcs -run
  TestRealCloudGCSStoreAndLedgerComposition -v` output (GCSStore/GCSLedger composed
  over the real Adapter).

No tokens, credentials, or raw auth headers appear in any of these files (verified by
grep before hashing, see manifest).

## Findings against B3/B4 requirements

1. **First create succeeds** — `TestRealCloudGCSWitnessQualification`: `CreateSuccess`.
2. **Exact duplicate idempotent** — same call replayed: `AlreadyExistsIdentical`.
3. **Conflicting bytes fail closed** — different payload, same key:
   `AlreadyExistsConflict`, `errors.Is(err, gcswitness.ErrConflict)` true.
4. **No overwrite** — `ReadExact` immediately after the conflicting attempt returned
   the original bytes unchanged.
5. **No alternate key fallback** — structural: `CreateExactIfAbsent`/
   `classifyCreateError` (gcswitness.go) operate on exactly the one `key` parameter
   throughout; no second `Object()` call against any other name anywhere in the
   package. Verified by source inspection, not a new runtime test.
6. **Exact-key read succeeds** — `ReadExact` returned the exact original bytes.
7. **Exists behaves correctly** — true for the created key, false for a never-created
   key.
8. **Object delete while retained fails** — real `403`, `"is subject to bucket's
   retention policy... and cannot be deleted or overwritten until <timestamp>"` — this
   held even *before* the lock (retention alone enforces it).
9. **Object overwrite while retained fails** — identical `403` condition, confirmed
   pre-lock.
10. **Retention reduction/removal fails after lock** — post-lock: retention removal →
    `"has a locked Retention Policy which cannot be removed"`; retention reduction to
    1s → `"Cannot reduce retention duration of a locked Retention Policy"`. Both real,
    both post-lock-specific (these would have been *allowed* pre-lock).
11. **Retained bytes remain unchanged** — pre-lock and post-lock object metadata
    (generation `1787163852531766`, md5 `mEWTtL/yVY2cPc09hzb5eQ==`, size 51 bytes) are
    byte-for-byte identical.
- **GCSStore/GCSLedger composition** — `TestRealCloudGCSStoreAndLedgerComposition`:
  `keypinning.GCSStore.Pin`/`.Get` round-tripped a real ECDSA P-256 pin (including
  independent fingerprint re-verification on read) against the real bucket, idempotent
  on retry; `compromiseledger.GCSLedger.Declare`/`.Status` round-tripped a real
  distrust record and correctly returned `StatusRequiresManualReview`.

## B4 — ambiguous write (fault-proxy)

**Not qualified this run — reported honestly as STILL_REQUIRED_FOR_S7, not
fabricated.** The existing `conformance/faultproxy.DropResponseAfterBackendSuccess`
mode's "handshake vs. real-RPC" distinction is a hardcoded byte-count heuristic
(`handshakeThreshold = 64`) calibrated for the Cloud Spanner emulator's gRPC
handshake. A real TLS session to `storage.googleapis.com` exchanges several
kilobytes during the TLS handshake alone (ClientHello, ServerHello, certificate
chain) -- reusing the existing heuristic as-is would misclassify the TLS handshake
itself as "the real request in flight" and sever the connection before the actual
HTTP create request is ever dispatched, which tests TLS-handshake interruption, not
the required "backend genuinely creates the object, client sees ambiguous failure"
scenario. A correctly calibrated variant is new engineering (a new fault mode aware
of TLS record boundaries or response-first-byte timing), not "reusing the existing
pattern" as instructed, and attempting it ad hoc against a live Google endpoint risked
producing flaky or misleading results rather than genuine qualification evidence. Per
the task's own instruction ("do NOT fake a safe result... report as
STILL_REQUIRED_FOR_S7 rather than fabricating evidence"), this is reported as not
qualified rather than forced.

## Cleanup status

Bucket Lock is irreversible by design; the retention policy (86400s, effective
2026-08-19T18:26:04.223Z) cannot be shortened or removed. **Earliest safe cleanup
time: 2026-08-20T18:26:04.223Z** (24h after lock effective time; the individual
witness objects' own `retention_expiration` timestamps fall within this window). No
delete/retention-bypass was attempted to accelerate cleanup, per instruction. The
bucket remains in `emg-adr043-disposable-witness`, labeled
`disposable=true,purpose=adr044-s7-prequal`, containing only qualification objects
created by this task (six objects total: two witness-shaped, two pin records, two
distrust records -- all listed in `bucket_metadata_current.json`'s companion object
listing, none pre-existing, none unrelated).
