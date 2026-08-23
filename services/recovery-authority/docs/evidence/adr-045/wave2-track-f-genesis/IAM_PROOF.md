# Phase 2 — IAM Domain-Separation Proof

## Live-tested (real denied API calls)

| Test | Result |
|---|---|
| Authority identity attempts real `AsymmetricSign` | Real `403 USER_PROJECT_DENIED` — the authority GSA has no grant on the signing project's API surface at all |
| Signer identity attempts real Spanner `CreateSession` against the authority database | Real `403 SERVICE_DISABLED` — Cloud Spanner API is not even enabled in the signer's own quota-project context, an even-earlier-layer denial |
| Signer identity attempts real GCS write to the witness bucket | Real `403`: `storage.objects.create` denied |
| Bootstrap identity (temporary) exercises real end-to-end genesis | **Succeeds** — this is the one principal actually authorized for this one-time operation |
| Signer identity attempts to run genesis (Phase 8 "unauthorized WIF principal") | Real `403`: denied even at the earliest witness-precondition read (`storage.objects.get` on the witness bucket) |

## Structurally verified (direct IAM policy inspection, real resource-scoped bindings)

- `gcloud projects get-iam-policy` for all three projects (`emg-platform-staging`, the signing project, the ledger project) returned **zero** bindings for any of the 6 qualification GSAs — no project-level Owner/Editor/Viewer, no project-level role of any kind. Every grant was bound to a specific resource (Spanner database, GCS bucket, or KMS key) via a purpose-built custom role.
- `gcloud iam service-accounts keys list --managed-by=user` returned **empty** for all 6 GSAs — zero static/user-managed keys anywhere.
- Pin-capture's KMS key policy contained only `raGenesisKmsPinCapture` (`cloudkms.cryptoKeyVersions.get`, `cloudkms.cryptoKeyVersions.viewPublicKey`) — no `useToSign` anywhere. **Pin-capture cannot sign.**
- Ledger-writer was never bound on the KMS key or the pin-store bucket at all (only the ledger bucket). **Ledger-writer cannot sign or write pins.**
- Authority and bootstrap's grants on the pin-store and ledger buckets were exclusively `raGenesisStorageReader` (`storage.objects.get`, `storage.buckets.get` — no `create`). **Verifier/runtime reads cannot mutate pin/ledger records.**
- No org- or folder-level binding was found affecting any qualification GSA (all 6 GSAs' effective policy above the project level was checked and found empty of any relevant grant).

No unexplained effective permission was found for any of the 6 qualification principals.
