# ADR-043 Blocker A — Real-GCP Destructive Qualification Evidence

## Scope

This directory preserves the evidence from the **destructive** Blocker A experiment:
whether an unexpired, Bucket-Lock-retained GCS witness object survives a genuine
Google Cloud project deletion and restoration, after the automatically-created
`projects.delete` lien is deliberately removed. This is the follow-on, destructive
counterpart to the non-destructive evidence in
`../real-gcp-safe-qualification/`, and reuses the same disposable project.

**Result: `BLOCKER_A_EXPERIMENT_RESULT = SURVIVED_PROJECT_DELETE_RESTORE`.**
**`BLOCKER_A_STATUS = EXPERIMENTALLY_PASSED`.**
**`PRODUCTION_APPROVAL_STATUS = NOT ESTABLISHED`.**

**This is experimental provider-observed qualification evidence, not production
approval.** See "What this does and does not establish" below.

## Experimental topology

| Field | Value |
|---|---|
| Test date/time (UTC) | 2026-08-16, 17:31–18:08 |
| Disposable Project ID | `emg-adr043-disposable-witness` |
| Project number | `617557656575` |
| Bucket (fresh, not reused from the safe test) | `emg-adr043-blockera-destructive-08657059` (region `US-CENTRAL1`) |
| Object | `witness/destructive-test-object-v1.txt` (87 bytes) |
| Retention period | 86400 seconds (24h) |
| Billing account (pre-existing association, re-linked after restore) | `01CDA5-613648-B7B26E` |
| Isolation | Project-level isolation as established in the safe-qualification phase; `emg-platform-staging` was never accessed, modified, or referenced at any point in this experiment. |

## Exact sequence of events

1. **Fresh bucket + object created and locked.** A new bucket (not the safe-test bucket) was created, retention set to 86400s, a deterministic 87-byte test object uploaded, and the retention policy locked via `lockRetentionPolicy?ifMetagenerationMatch=3` → `isLocked: true`. See `bucket-metadata-locked-pre-deletion.json`, `object-metadata-before-lock.json`.
2. **Pre-lien-removal enforcement verified.** Object delete, object overwrite, retention reduction, and retention removal all independently returned `403` (`retentionPolicyNotMet` / `forbidden`). See `sanitized-responses/02`–`05`.
3. **Lien identified.** One lien matched (parent = this project, origin `storage.googleapis.com`, restriction `resourcemanager.projects.delete`). See `lien-before-removal.json`. (Note: this lien's `createTime` predates this bucket — it is the same project-level lien object created during the earlier safe-qualification test; Bucket Lock liens appear to be a per-project singleton by origin+restriction, not created fresh per bucket.)
4. **Gate 1 passed.** Object re-confirmed still retention-protected immediately before lien removal.
5. **Lien removed.** Completed as a manual, explicitly-authorized action outside automated tooling (a platform-level safety control blocked automated execution of this specific command); verified via `liens list` returning 0 items.
6. **Post-lien retention enforcement re-verified.** A fresh delete attempt against the object, immediately after lien removal, still returned `403 / retentionPolicyNotMet` — proving lien removal does not itself weaken Bucket Lock enforcement. See `sanitized-responses/06`. `P0_CRITICAL` did not trigger.
7. **Gate 2 passed.** All 8 required assertions (project identity, object existence/hash/generation, retention active, bucket locked, lien count 0, no unexpected resources, staging untouched) independently verified.
8. **Project deletion requested.** `DELETE .../projects/emg-adr043-disposable-witness` → `HTTP 200`. Immediately confirmed via `projects.describe`: `lifecycleState: DELETE_REQUESTED`. See `sanitized-responses/07`, `project-state-delete-requested.json`.
9. **Project restoration requested immediately** (~35 seconds later). `POST .../projects/emg-adr043-disposable-witness:undelete` → `HTTP 200`. Immediately confirmed: `lifecycleState: ACTIVE`. See `sanitized-responses/08`, `project-state-active-after-restore.json`.
10. **Billing-disabled state discovered.** The very first post-restore object read failed — not with "not found," but with `403: The billing account for the owning project is disabled in state absent`. Independently confirmed via `billing.projects.describe`: `billingEnabled: false`, `billingAccountName: ""`. **`projects.undelete` restores project `lifecycleState` but does not automatically restore the Cloud Billing association.** See `sanitized-responses/09`, `billing-disabled-after-restore.json`.
11. **Billing re-linked**, narrowly and explicitly authorized, to the project's own pre-existing billing account only: `gcloud billing projects link emg-adr043-disposable-witness --billing-account=01CDA5-613648-B7B26E` → `billingEnabled: true`. See `billing-relink-response.json`.
12. **Original bucket and object read successfully, immediately** — no propagation delay was needed once billing was re-linked. See `bucket-metadata-post-relink.json`, `object-metadata-post-relink.json`.
13. **Identity verified**: generation, CRC32C, MD5 (provider-reported) and SHA-256 (independently recomputed from downloaded bytes) all matched the pre-deletion values exactly. See `object-bytes-post-relink.txt` and the manifest.
14. **Retention and lock state verified unchanged**: `retentionPeriod: 86400`, same `effectiveTime`, `isLocked: true`.
15. **Post-restore retention enforcement re-verified — the decisive check.** A final delete attempt against the restored object returned the identical `403 / retentionPolicyNotMet`, with the identical expiration timestamp as every earlier check. See `sanitized-responses/10`.

## Decisive results

| Check | Result |
|---|---|
| Original bucket survived | **PASS** — identical generation/metageneration/retention config |
| Original object survived | **PASS** — read succeeded post-relink |
| Generation identity | **PASS** — `1786901627964283`, unchanged |
| Byte identity | **PASS** — SHA-256 `cc605b9773c3f991a9f5afcd68e56bb3dffefc0ec5e1ca169da726996f0c236d` unchanged; provider CRC32C `3UsnGQ==` and MD5 `Vwg9TkRDjriAbYhV7IJGLQ==` unchanged |
| Retention state survived | **PASS** — `retentionPeriod: 86400`, same `effectiveTime` |
| Lock state survived | **PASS** — `isLocked: true` |
| Post-restore delete protection | **PASS** — real `403 / retentionPolicyNotMet` |

Nothing was recreated. Every check above was performed against the exact original
bucket and the exact original object.

## Operational recovery requirement (must be documented in any ADR-043 runbook)

```
PROJECT RESTORE
  → VERIFY lifecycleState == ACTIVE
  → VERIFY billing association (gcloud billing projects describe)
  → IF billingEnabled == false:
        RE-LINK the previously-approved billing account
        (gcloud billing projects link <project> --billing-account=<account>)
  → VERIFY billingEnabled == true
  → ONLY THEN attempt witness bucket/object read or verification
```

This is **not** data loss and must not be characterized as such. It is an
**operational availability dependency**: the witness data survives regardless, but a
real recovery procedure must include the billing re-link step, or Cloud Storage
access remains blocked indefinitely after a real project restore.

## What this does and does not establish

**`BLOCKER_A_EXPERIMENT_RESULT = SURVIVED_PROJECT_DELETE_RESTORE`** — direct,
provider-observed evidence (not documentation, not assumption, not recreated data)
that an unexpired, Bucket-Lock-retained object survives project deletion and
restoration, with byte identity and retention/lock enforcement fully intact, in this
one disposable-project trial.

**`PRODUCTION_APPROVAL = NOT ESTABLISHED`.** This single experimental trial does not
constitute production approval, governance sign-off, or same-organization/
same-billing-account risk acceptance. Those remain separate, unresolved questions.
The billing-relink operational dependency discovered here is itself a new fact that
any production readiness review must account for.

## Evidence handling notes

Raw `--log-http` CLI output was reviewed but is **not** included in this directory:
it contained the authenticated account's email address (in gcloud's own diagnostic
text) and local sandbox filesystem paths — the same categories excluded in the prior
safe-qualification evidence. It never contained the actual bearer token (redacted by
`gcloud` itself) or any cookie. Every fact relevant to the qualification claim has
been carried into hand-verified sanitized extracts. See `evidence-manifest.md` for
the full file list, integrity hashes, and an explicit identity cross-check between
pre-deletion and post-restore state.
