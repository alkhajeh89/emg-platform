# Track E — Cleanup Record

Performed after evidence capture, in this order:

1. Deleted the `ra-k8s-qual` Kubernetes namespace in the real `emg-staging` cluster — removed both qualification Deployments/Pods/Services/NetworkPolicies/ExternalSecrets/Secrets/SecretStore and all three qualification KSAs in a single action. Confirmed gone (`NotFound`).
2. Removed the `roles/iam.workloadIdentityUser` bindings for the authority GSA and the ESO-fetch GSA (both in `emg-platform-staging`); the signer GSA's binding was removed automatically as part of its project's deletion in step 5.
3. Deleted both qualification GSAs directly from `emg-platform-staging` (`ra-authority-k8squal`, `ra-eso-k8squal`), since `emg-platform-staging` is a real, ongoing project not itself being torn down.
4. Deleted the 3 qualification-only GCP Secret Manager secrets (`emg-ra-k8s-qual-signer-tls-crt`, `emg-ra-k8s-qual-signer-tls-key`, `emg-ra-k8s-qual-ca-bundle`) from `emg-platform-staging`.
5. Deleted the qualification-only Artifact Registry repository (`ra-k8s-qual`, `me-central1`) from `emg-platform-staging`, including both real container images built for this qualification.
6. Disabled (never destroyed) the Track E KMS key version — see `tracke_key_disabled_state.json` (`state: DISABLED`).
7. Deleted the fresh disposable signing project (`emg-ra-signer-k8squal-a970703a`) via `gcloud projects delete` — this removes the signer GSA, the KMS key ring/key, and every remaining qualification IAM binding as part of standard project teardown. Confirmed in GCP's standard ~30-day recoverable deletion window, not an irreversible purge.

**Verified after cleanup:**
- No qualification namespace, pod, Service, NetworkPolicy, Secret, or KSA remains anywhere in the real `emg-staging` cluster.
- `emg-platform-staging`'s service-account list contains exactly the same two entries it had before this qualification (`emg-cloudsql-staging`, the default compute SA) — identical to Track D's own pre/post baseline.
- The real `emg-staging` namespace's Pods, Deployments, Services, ReplicaSets, Jobs, and KSAs are byte-for-byte unchanged from before Track E began (same object ages, same restart counts consistent with elapsed time, zero new/modified/removed objects).
- `kube-system` and its DNS infrastructure (kube-dns, node-local-dns) are entirely untouched — no NetworkPolicy was ever added there, no workload was modified there.
- The Track C/D disposable projects remain exactly as previously found (`DELETE_REQUESTED`), never touched, never undeleted.
- The real, Bucket-Locked ADR-043 evidence bucket was never referenced or touched at any point in Track E.
- The temporary repository-scoped `roles/artifactregistry.reader` grant to the GKE node's default compute service account was removed automatically along with the Artifact Registry repository's own deletion (an IAM policy bound to a deleted resource cannot persist).
