# Phase 9 — Bootstrap Privilege Revocation

After the real genesis (`GENESIS_RESULT.md`) and its idempotent rerun (`IDEMPOTENCY.md`) were both confirmed complete:

1. `recovery-bootstrap-deployment`'s `roles/iam.workloadIdentityUser` binding (`ra-genesis-bootstrap` KSA → GSA) was removed via `gcloud iam service-accounts remove-iam-policy-binding`.
2. A **fresh** pod, created after the removal call, bound to the `ra-genesis-bootstrap` KSA, attempted `gcloud auth print-access-token`:

```
ERROR: gcloud crashed (MetadataServerException): The request is rejected.
```

Real, immediate denial for a fresh credential-acquisition attempt. This trial did not itself bracket the exact propagation boundary (unlike Track D's dedicated timing trial) — by the time the fresh pod had scheduled and started (~15s of pod-startup latency alone), the binding removal had already taken effect. This is consistent with, not contradictory to, Track D's own measured WIF-binding-removal propagation window (31s–89s in that trial).

3. Ordinary `recovery-authority-runtime` (a completely separate GSA/WIF binding, never touched by this revocation) was independently confirmed still fully functional:

```
GET /healthz → ok
GET /readyz  → ready
```

Distinguishing already-issued-credential lifetime from fresh-acquisition denial: this trial tested only fresh acquisition (a new pod created after revocation). Already-issued-token persistence-after-revocation was already exhaustively, empirically qualified in Wave 2 Track D (`REVOCATION_TIMING.md`) — the underlying GKE WIF/OAuth2 mechanism is identical and unchanged, so it was not redundantly re-measured here.
