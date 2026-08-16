# ADR-043 Blocker A — Real-GCP Safe Bucket Lock Qualification Evidence

## Summary

This directory preserves the evidence from the `SAFE_REAL_GCP_TEST_PLAN` execution
against a real, disposable Google Cloud project, run in support of ADR-043 Blocker A
(Bucket Lock provider-authority qualification). It records **real, first-hand provider
responses** — not documentation summaries and not emulator output — for object/bucket
retention enforcement, locked-policy irreversibility, the automatic project lien, and a
safe (non-destructive) project-deletion-with-lien check.

**This evidence does NOT close Blocker A.** It confirms Bucket Lock and its lien behave
as documented at the object/bucket/lien level. It does not and cannot answer the
remaining open question — whether a retained object survives project deletion *after*
the lien is removed — because the lien was deliberately never removed in this phase.
See `BLOCKER_A_STATUS` below.

## Test identity

| Field | Value |
|---|---|
| Test date/time (UTC) | 2026-08-16, 10:21–10:41 |
| Disposable Project ID | `emg-adr043-disposable-witness` |
| Project number | `617557656575` |
| Bucket | `emg-adr043-bucketlock-test-a09a5162` (region `US-CENTRAL1`) |
| Provider | Google Cloud Storage (JSON API, `gcloud storage` CLI surface) |
| Isolation | Project-level isolation confirmed (created for this test, zero pre-existing resources). Billing account (`01CDA5-613648-B7B26E`) is shared with `emg-platform-staging` — explicitly waived by the requester for this SAFE phase only; `emg-platform-staging` itself was never accessed, modified, or tested against. |

## Results

| Step | Action | Result |
|---|---|---|
| Minimum retention | `retention-period=1s`, then upload | **Accepted.** `retention_expiration = creation_time + 1s`, HTTP 200. No documented or observed lower bound exists; 1 second is the smallest value tested and it succeeded. |
| Lock | `lockRetentionPolicy` with `ifMetagenerationMatch=4` | **HTTP 200**, `retentionPolicy.isLocked: true`. Confirmed irreversible per provider tooling (the CLI itself requires an explicit, non-`--quiet`-overridable interactive confirmation before locking). |
| Object delete (while retained) | `DELETE` on the retained object | **HTTP 403 / `retentionPolicyNotMet`** |
| Object overwrite (while retained) | `PUT` replacing the retained object | **HTTP 403 / `retentionPolicyNotMet`** |
| Bucket delete (non-empty, retained) | `DELETE` on the bucket | **HTTP 409 / `conflict`** ("The bucket you tried to delete is not empty.") |
| Retention reduction (locked) | `PATCH` retentionPeriod 180→10 | **HTTP 403 / `forbidden`** — see discrepancy note below |
| Retention removal (locked) | `PATCH` retentionPolicy→null | **HTTP 403 / `retentionPolicyNotMet`** |
| Lien creation | `resourcemanager liens list` after lock | **Present.** Restriction `resourcemanager.projects.delete`, origin `storage.googleapis.com`, created at the same instant as the lock call. |
| Project deletion with lien | `projects delete` while lien present | **HTTP 400 / `FAILED_PRECONDITION` / reason `PROJECT_DELETE_LIEN`.** Request rejected outright. |
| Project state | `projects describe` immediately before/after the delete attempt | **`lifecycleState: ACTIVE`, unchanged.** Project never entered `DELETE_REQUESTED`. |
| Object survival | Re-read after the rejected delete attempt | **Byte-identical.** SHA-256 `a3b05ac9e7bec756e8a554f8f25f9e20b606244ac50ff5c12e9b5c37a8430332` matches the original test file exactly; object generation (`1786876609712154`) unchanged. |
| Cleanup | Delete object, then bucket, after natural retention expiry | **Both succeeded (HTTP 204 each).** No protection was bypassed or weakened to achieve this. |
| Lien after cleanup | `resourcemanager liens list` after bucket deletion | **Still present, unchanged.** The lien does not auto-remove when the retained resource is deleted; it was left in place, untouched, per the standing prohibition on lien removal in this phase. |

**P0 found: none.** The project-deletion request was correctly rejected in every observed respect; no operation required weakening a security invariant to complete.

## Observed provider behavior that differed from prior documentation research (P1)

1. **Locked-retention reduction**: official documentation (`storage/docs/json_api/v1/status-codes`) documents this as **HTTP 400 / `badRequestException`**. The real, observed response was **HTTP 403 / `forbidden`**. See `sanitized-responses/05-reduce-locked-retention-403.json`.
2. **Bucket deletion while non-empty (JSON API)**: prior research found the XML API returns a distinct `BucketNotEmpty` reason under HTTP 409, but could not confirm an equivalent distinct reason on the JSON API. The real, observed JSON API response uses the generic **`reason: "conflict"`** under HTTP 409, distinguished only by the `message` text. See `sanitized-responses/04-delete-nonempty-bucket-409.json`.

Real provider behavior is treated as authoritative over documentation prose in both cases.

## What this evidence proves and does not prove

**Proven (object/bucket/lien level, real provider, this session):** minimum retention acceptance, lock irreversibility, object delete/overwrite enforcement, bucket-delete-while-non-empty enforcement, locked-policy reduce/remove enforcement, automatic lien creation and its exact restriction, and that the lien blocks the project-deletion *request* itself (not merely delays final purge) — with the project provably remaining `ACTIVE` and the retained object provably byte-identical afterward.

**Not proven, and explicitly not attempted in this phase:** whether a retained object survives project deletion *after* the lien is removed. **Lien removal and the project-deletion experiment were NOT executed.** The lien on `emg-adr043-disposable-witness` remains in place as of this evidence capture; the project cannot currently be deleted through normal means.

## BLOCKER_A_STATUS

`OPEN_PROVIDER_CONFIRMATION_REQUIRED` — unchanged by this evidence. Closing Blocker A requires the separately-authorized, still-unexecuted dangerous experiment (remove the lien while an object remains under retention, request project deletion, and observe/attempt restoration).

## Evidence handling notes

Raw `--log-http` CLI output was reviewed but is **not** included in this directory: it contained the authenticated account's email address and local sandbox filesystem paths in diagnostic text (though never the actual bearer token, which `gcloud`'s own logging already redacts). All HTTP request/response evidence here is a hand-verified **sanitized extract** — status code, reason, message, and the specific resource fields relevant to the claim being evidenced — with headers, upload session IDs, user-agent/client-identity strings, and local paths removed. See `evidence-manifest.md` for the full file list and integrity hashes.
