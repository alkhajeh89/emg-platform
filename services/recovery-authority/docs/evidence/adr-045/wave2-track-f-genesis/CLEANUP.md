# Phase 11 — Cleanup

Performed after all evidence was captured, in this order:

1. Deleted the `ra-genesis-qual` Kubernetes namespace in the real `emg-staging` cluster (removed all qualification Deployments/Pods/Services/NetworkPolicies/ExternalSecrets/Secrets/SecretStore/KSAs in one action).
2. Removed the `roles/iam.workloadIdentityUser` bindings for `ra-genesis-authority` and `ra-genesis-eso` in `emg-platform-staging` (the bootstrap binding was already removed in Phase 9).
3. Deleted the `ra-genesis-authority`, `ra-genesis-eso`, and `ra-genesis-bootstrap` GSAs directly from `emg-platform-staging` (a real, ongoing project, not itself torn down).
4. Deleted the 3 qualification-only custom IAM roles in `emg-platform-staging` (`raGenesisSpannerFull`, `raGenesisSpannerBootstrap`, `raGenesisStorageWriter`).
5. Deleted the qualification-only Artifact Registry repository (`ra-genesis-qual`, `me-central1`) from `emg-platform-staging`, including all 5 real container images built for this qualification.
6. Deleted the disposable Spanner instance `ra-genesis-qual` (and its `authority` database) from `emg-platform-staging`.
7. Disabled (never destroyed) the Track F KMS key version — see `trackf_key_disabled_state.json` (`state: DISABLED`).
8. Deleted the fresh disposable signing project (`emg-ra-genesis-signer-4185f50f`) via `gcloud projects delete` — removes the signer/pin-capture GSAs, the KMS key ring/key, the pin-store bucket, and their custom IAM roles/bindings as part of standard project teardown (GCP's standard ~30-day recoverable window, not an irreversible purge).
9. Deleted the fresh disposable compromise-ledger project (`emg-ra-genesis-ledger-7161f246`) via `gcloud projects delete` — removes the ledger-writer GSA, the ledger bucket, and its custom IAM roles/bindings, same recoverable window.

## Deliberately NOT deleted (documented, not bypassed)

The witness bucket (`emg-ra-genesis-witness-qual`, in `emg-platform-staging`) and its 3 objects remain under **real, active Bucket Lock retention** and cannot be deleted before their retention expires:

| Object | Retention expires (UTC) |
|---|---|
| Real completed genesis (`.../01a030b9-.../01a030b9-.../1.json`) | 2026-08-24T22:30:48Z |
| Witness-conflict test object (bogus content, `.../01a030c3-.../01a030c3-.../1.json`) | 2026-08-24T22:39:25Z |
| Disabled-KMS-propagation-test genesis (`.../01a030c8-.../01a030c8-.../1.json`) | 2026-08-24T22:40:58Z |

Per this task's explicit instruction, retention was never bypassed. The bucket and these objects must be deleted through normal means after 2026-08-24T22:40:58Z UTC (the latest expiration), as a follow-up action outside this evidence-capture session.

**Verified after cleanup:**
- No qualification namespace, pod, Service, NetworkPolicy, Secret, or KSA remains anywhere in the real `emg-staging` cluster.
- `emg-platform-staging`'s service-account list contains exactly the same two entries it had before this qualification (`emg-cloudsql-staging`, the default compute SA) — identical to the Track D/E baseline.
- The real `emg-staging` namespace's Pods, Deployments, Services, ReplicaSets, Jobs, and KSAs are byte-for-byte unchanged from before Track F began.
- `kube-system` is entirely untouched.
- The Track C/D/E disposable projects remain exactly as previously found (`DELETE_REQUESTED` or already purged), never touched, never undeleted.
- The real, Bucket-Locked ADR-043 evidence bucket was never referenced or touched at any point in Track F.
