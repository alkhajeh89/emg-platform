# Phase 15 — Cleanup

Performed after all evidence was captured, in this order:

1. Deleted the disposable Spanner instance `s7-processdeath` (and its `authority` database) from `emg-ra-s7-spanner-3400f9e2`. Confirmed via successful `gcloud spanner instances delete`.
2. Attempted to delete the disposable project `emg-ra-s7-spanner-3400f9e2` via the normal, recoverable `gcloud projects delete` mechanism.

## Real, expected Bucket Lock behavior encountered

Project deletion **failed** with:

```
FAILED_PRECONDITION: A lien to prevent deletion was placed on the project by [storage.googleapis.com].
Remove the lien to allow deletion.
reason: PROJECT_DELETE_LIEN
```

This is a genuine, additional real-cloud confirmation of Bucket Lock's guarantee, consistent with (and extending) ADR-044 §11/§12's already-qualified findings: the locked retention policy on `gs://emg-s7-processdeath-witness/` placed a real **project-level deletion lien** — strong enough to block not just bucket/object deletion, but the entire project's deletion, until the retention period expires. **This lien was not removed, bypassed, or worked around.** Per this task's explicit instruction ("Do not bypass retention"), the project is left in its current, active-but-otherwise-cleaned-up state.

**Required follow-up (outside this task, after the following date):**

| Resource | Retention expires (UTC) | Action required after expiry |
|---|---|---|
| `gs://emg-s7-processdeath-witness/` (and its lien) | 2026-08-24T23:28:07Z | Delete the bucket/objects, then retry `gcloud projects delete emg-ra-s7-spanner-3400f9e2` |

## Verified after cleanup

- The disposable Spanner instance/database no longer exist (no further Spanner cost accrues).
- `emg-platform-staging` was never referenced or touched at any point in this task — the entire S7 qualification used only the fresh, disposable `emg-ra-s7-spanner-3400f9e2` project, per explicit instruction.
- No existing `emg-staging` Kubernetes workload was touched — this qualification used no Kubernetes topology at all.
- No repository file outside the new evidence directory and the new test file was modified during the qualification phases (confirmed via `git status` in `FULL_VALIDATION.md`).
