# Track D — Cleanup Record

Performed after evidence capture, in this order:

1. Deleted the `ra-wif-qual` Kubernetes namespace in the real `emg-staging` cluster — this removed both qualification pods, both qualification KSAs, and any qualification-only child objects in a single action. Confirmed gone (`NotFound`).
2. Removed the remaining `roles/iam.workloadIdentityUser` binding on the signer GSA (the authority GSA's binding was already removed during the Phase 8 revocation test).
3. Deleted the authority GSA (`ra-authority-wifqual@emg-platform-staging.iam.gserviceaccount.com`) directly, since `emg-platform-staging` is a real, ongoing project that is not itself being torn down.
4. Disabled (never destroyed) the Track D KMS key version — see `trackd_key_disabled_state.json` (`state: DISABLED`).
5. Deleted the fresh disposable signing project (`emg-ra-signer-wifqual-8a1323ba`) via `gcloud projects delete` — this removes the signer GSA, the KMS key ring/key, and every remaining qualification IAM binding as part of standard project teardown. Confirmed `DELETE_REQUESTED` (GCP's standard ~30-day recoverable window, not an irreversible purge).

**Verified after cleanup:**
- No qualification namespace, pod, or KSA remains anywhere in the real `emg-staging` cluster.
- `emg-platform-staging`'s service-account list contains exactly the same two entries it had before this qualification (`emg-cloudsql-staging`, the default compute SA) — the qualification authority GSA is gone, nothing else was touched.
- The real `emg-staging` namespace's KSA list is unchanged from Phase 1's initial inventory (zero `recovery-authority`/`recovery-signer` KSAs, exactly as found before Track D began).
- The Track C disposable projects (`emg-ra-signing-qual-db77c759`, `emg-ra-ledger-qual-922b972d`) remain exactly as Track D found them: `DELETE_REQUESTED`, never touched, never undeleted.
- `emg-platform-staging`'s real workloads, real KSAs, and the real, Bucket-Locked ADR-043 evidence bucket were never referenced or touched at any point in Track D.
