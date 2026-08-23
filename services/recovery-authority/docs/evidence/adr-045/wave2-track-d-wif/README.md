# Wave 2 Track D — Real Workload Identity Federation Qualification

**Date:** 2026-08-22 – 2026-08-23
**Authoritative start commit:** `2cdbc118f3ffdf9aadeca42fabc77c7a11b0c5c4`
**Scope:** qualify the real GKE Workload Identity Federation identity path for the Recovery Authority / Recovery Signer topology and prove it preserves the principal/capability separation established by ADR-044, ADR-045, S4–S6, and Track C.
**Explicitly out of scope, not started:** Track E (Kubernetes/TLS qualification beyond identity), end-to-end genesis, S7.
**Does not prove:** ADR-045 §15A production administrative independence — this is a disposable, same-organization qualification. Production still requires the separately-governed Cloud Identity/Workspace trust-domain realization already selected by governance.

## Cloud/cluster inventory used

| Resource | Identity | Notes |
|---|---|---|
| Authority-side project | `emg-platform-staging` (existing, real, ACTIVE) | Reused per task guidance ("prefer existing staging as the authority-side qualification domain where safe") — only a **new, dedicated** GSA was created in it; no existing resource touched |
| GKE cluster | `emg-staging` (`emg-platform-staging`, `me-central1-a`, real, `RUNNING`) | Workload Identity Federation already enabled at the cluster level (`workloadPool: emg-platform-staging.svc.id.goog`) — **but no KSA in this cluster had ever actually used it before this qualification** (see Finding 0 below) |
| Signer-side project | `emg-ra-signer-wifqual-8a1323ba` (new, disposable) | Track C's signing project was deleted and deliberately **not** resurrected; a fresh project was created per task instruction |
| Track D KMS key | `.../keyRings/ra-trackd-ring/cryptoKeys/ra-trackd-key/cryptoKeyVersions/1` | `EC_SIGN_P256_SHA256`, `SOFTWARE`, fresh, Track-D-only — never reuses a Track C key |
| Authority GSA | `ra-authority-wifqual@emg-platform-staging.iam.gserviceaccount.com` | Zero KMS/Spanner/GCS grants anywhere — capability is proven absent by construction, not merely by a denied call |
| Signer GSA | `ra-signer-wifqual@emg-ra-signer-wifqual-8a1323ba.iam.gserviceaccount.com` | `roles/cloudkms.signer` on the Track D key only |
| Qualification namespace | `ra-wif-qual` (real, in the `emg-staging` cluster) | Isolated from the real `emg-staging` namespace and every real EMG workload |
| Authority KSA | `ra-authority-qual` (in `ra-wif-qual`) | Annotated to the authority GSA |
| Signer KSA | `ra-signer-qual` (in `ra-wif-qual`) | Annotated to the signer GSA (cross-project WIF binding — mirrors the real production topology's same-cluster/cross-project shape) |

## Finding 0 (honest, load-bearing): no pre-existing KSA→GSA WIF usage in this cluster

Before this qualification, **zero** KSAs in the real `emg-staging` cluster carried an `iam.gke.io/gcp-service-account` annotation, and the cluster's one existing GSA (`emg-cloudsql-staging`) had an empty IAM policy (no `workloadIdentityUser` binding to anything). Workload Identity Federation is enabled at the cluster level, but **Track D is the first real, end-to-end exercise of the KSA→GSA annotation + IAM-binding pattern in this cluster** — not a reuse of an already-proven precedent. This is reported plainly rather than implied otherwise.

## Positive qualification (real tokens, real capability)

- **Authority**: pod bound to `ra-authority-qual` correctly resolved its identity, via the real GKE metadata server, to `ra-authority-wifqual@emg-platform-staging.iam.gserviceaccount.com` — confirmed via both the metadata-server `/email` endpoint and `gcloud auth list`.
- **Signer**: pod bound to `ra-signer-qual` correctly resolved to `ra-signer-wifqual@...`, and used its real WIF-issued credential to perform a genuine `cryptoKeyVersions.asymmetricSign` call against the real Track D KMS key, receiving a genuine 96-byte ECDSA signature — the definitive positive proof of the signer-side identity chain end to end.

## Negative qualification (cross-principal denial, real 403s)

All of the following were exercised as real API calls against real GCP, from real pods running under their real WIF-issued identity (not simulated):

| Principal | Denied capability | Real result |
|---|---|---|
| Authority | Impersonate signer GSA | `IAM_PERMISSION_DENIED` (`iam.serviceAccounts.getAccessToken`) |
| Authority | `AsymmetricSign` on the signing project's key | `USER_PROJECT_DENIED` (`serviceusage.services.use`) — denied at an even earlier layer than the KMS permission itself |
| Authority | Create a service-account key | `IAM_PERMISSION_DENIED` (`iam.serviceAccountKeys.create`) |
| Authority | Impersonate an unrelated GSA (`emg-cloudsql-staging`) | `IAM_PERMISSION_DENIED` |
| Authority | Modify project IAM | `SERVICE_DISABLED` (Cloud Resource Manager API never enabled) |
| Signer | Impersonate authority GSA | `SERVICE_DISABLED` (`iamcredentials.googleapis.com` never enabled in the signing project) |
| Signer | Create a service-account key | `SERVICE_DISABLED` (`iam.googleapis.com`) |
| Signer | Impersonate an unrelated GSA | `SERVICE_DISABLED` |
| Signer | Read/modify its own key's IAM policy | `IAM_PERMISSION_DENIED` (`cloudkms.cryptoKeys.getIamPolicy`) |

**No case above resolved to success.** Several denials occur at an earlier layer than a bare IAM permission check (API not enabled, quota-project denied) — this reflects genuinely minimal API surface enablement, not a weaker test.

## Trust-boundary attacks (Phase 6 / attack matrix A–D, P)

| Attack | Result |
|---|---|
| Correct KSA + correct namespace | **Succeeds** (the two positive cases above) |
| Same KSA *name*, wrong namespace, same annotation | **Denied** — real `403` on token issuance (`iam.serviceAccounts.getAccessToken`); the metadata-server `/email` endpoint still echoed the claimed GSA (it only reflects the local annotation), but the real token-minting call correctly rejected it, proving capability is gated by GCP's own IAM binding, never by the annotation |
| Wrong KSA name, correct namespace, imposter annotation | **Denied** — identical real `403` |
| Default/unannotated KSA | Receives a token, but scoped to the **bare, unmapped pool identity** (`emg-platform-staging.svc.id.goog`), which holds zero IAM grants anywhere — any actual use fails |
| Authority ↔ signer GSA collapse | Disproven by construction and by identity introspection — two distinct GSAs in two distinct projects |

## Revocation / propagation (Phase 8)

See `REVOCATION_TIMING.md`. Summary: binding removal converged within roughly 30–90 seconds in this trial (faster than, and consistent with, Google's general ~2–7 minute IAM-propagation guidance); an already-issued token remained valid until its own natural expiry regardless of the binding removal — reported honestly, not rounded to "instant."

## IAM inheritance (Phase 7)

Both qualification GSAs' own IAM policies contain **exactly one binding each** — the single, exact `workloadIdentityUser` subject shown in the inventory table above. Neither GSA has any project-level, folder-level, or organization-level binding of any kind (checked directly against `emg-platform-staging`, `emg-ra-signer-wifqual-8a1323ba`, and the organization). Declared IAM equals effective IAM exactly; no inherited path was found that could bridge the authority/signer domains or grant either principal `Owner`/`Editor`/`storage.admin`/`cloudkms.admin`/any IAM-administration capability.

## Static credential check

No JSON key file, no `GOOGLE_APPLICATION_CREDENTIALS` environment variable, and no static/portable credential of any kind was found on either pod's filesystem or environment. `gcloud`'s own internal `credentials.db` is an ephemeral, ADC-derived token cache tied to the pod's own metadata-server session — not a portable secret — and this distinction is stated explicitly rather than glossed over.

## Provider fact-check

See `PROVIDER_FACT_CHECK.md`.

## Cleanup

See `CLEANUP.md`.

## Limitations (stated explicitly)

- This is a **disposable, same-organization** qualification. It proves the WIF mechanism and the authority/signer principal separation. It does **not** prove ADR-045 §15A production administrative independence, which requires a genuinely separate Cloud Identity/Workspace trust domain, not yet realized.
- ATTACK_F/Q/R/S (signer→Spanner mutation, signer→pin-capture write, pin-capture→sign, ledger-writer→sign) were not re-exercised against a live resource this wave because no Spanner/pin-store/ledger resource exists in Track D's scope (Track D is identity-federation-only; those specific boundaries were already empirically qualified with real resources in Wave 1 Track A/B and Wave 2 Track C). Both qualification GSAs hold **zero** grant on any such resource, so these remain structurally denied by absence of any binding, consistent with the already-qualified least-privilege model — not re-proven via a new live resource here to avoid recreating Track A/B/C's already-torn-down infrastructure merely for redundant coverage.
- ATTACK_O (a running pod changes its own KSA association) was not empirically attempted: a Pod's `spec.serviceAccountName` is immutable once created, enforced by the Kubernetes API server itself — a structural guarantee of Kubernetes, not a provider-specific behavior requiring empirical qualification.
