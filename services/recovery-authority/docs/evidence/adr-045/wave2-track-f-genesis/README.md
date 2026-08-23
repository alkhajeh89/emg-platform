# Wave 2 Track F — End-to-End Real-Cloud Genesis Qualification

**Date:** 2026-08-23
**Authoritative start commit:** `8b5a1f35845555c2bf113dac564fdf3e7eb65fa2` (Track E, CI green)
**Scope:** prove one complete, governed, real-cloud `bootstrap.ExecuteGenesis` flow against disposable infrastructure, integrating every boundary already qualified in Tracks A–E: dual-control approvals → bootstrap preconditions → pinned signing key → compromise-ledger check → recovery-authority → authenticated TLS signerrpc → real Cloud KMS signature → real Spanner commit → classification → real immutable GCS witness → durable bootstrap evidence.
**Explicitly out of scope, not started:** Track E remains the last completed Kubernetes/TLS track; S7; production deployment; production approval.
**Does not prove:** ADR-045 production administrative independence (unchanged from Track D/E — disposable same-organization environment only).

## Topology

| Domain | Resource | Notes |
|---|---|---|
| Authority/witness | `emg-platform-staging` (existing project, reused per Track D/E precedent) | New, dedicated: Spanner instance `ra-genesis-qual` (100 PU, `regional-me-central1`), database `authority` (real DDL from `scripts/emulator/schema.sql`), witness bucket `emg-ra-genesis-witness-qual` (versioned, Bucket Lock retention **locked** at 1 day before genesis) |
| Signing | `emg-ra-genesis-signer-4185f50f` (fresh disposable project, deleted at cleanup) | KMS key ring `ra-genesis-ring`, key `ra-genesis-key`, version 1 (`EC_SIGN_P256_SHA256`, `SOFTWARE`); pin-store bucket `emg-ra-genesis-pinstore-qual` |
| Compromise ledger | `emg-ra-genesis-ledger-7161f246` (fresh disposable project, **third**, distinct project, deleted at cleanup) | Ledger bucket `emg-ra-genesis-ledger-qual` |
| Kubernetes | `ra-genesis-qual` namespace, real `emg-staging` GKE cluster (deleted at cleanup) | Real `recovery-authority`/`recovery-signer` Deployments built from the now-fixed base manifests (Track E's fsGroup + DNS-egress fixes inherited automatically); fresh qualification TLS CA/cert; real WIF bindings for authority/signer/pin-capture/ledger-writer/bootstrap/ESO identities |
| Genesis orchestrator | `trackfgenesis`/`trackfpincapture`/`trackfledgerwrite` (disposable Go binaries, real unmodified `bootstrap`/`spannercommit`/`gcswitness`/`keypinning`/`compromiseledger`/`signerrpc` packages via a local `replace` directive) | Never committed to the repository; scratchpad-only, deleted with the rest of Track F's disposable resources |

## Principal bindings (real WIF, real custom IAM roles, exact resource scoping)

| Principal | KSA → GSA | Grants |
|---|---|---|
| `recovery-authority-runtime` | `ra-genesis-authority` → `ra-genesis-authority@emg-platform-staging.iam.gserviceaccount.com` | `raGenesisSpannerFull` on the `authority` database; `raGenesisStorageWriter` on the witness bucket; `raGenesisStorageReader` (cross-project) on pin-store + ledger buckets |
| `recovery-signing` | `ra-genesis-signer` → `ra-genesis-signer@emg-ra-genesis-signer-4185f50f.iam.gserviceaccount.com` | `raGenesisKmsSigner` (`cloudkms.cryptoKeyVersions.useToSign`) on the signing key only |
| `recovery-bootstrap-deployment` | `ra-genesis-bootstrap` → `ra-genesis-bootstrap@emg-platform-staging.iam.gserviceaccount.com` | `raGenesisSpannerBootstrap` (write-only, no read/select) on the `authority` database; `raGenesisStorageWriter` on the witness bucket; `raGenesisStorageReader` (cross-project) on pin-store + ledger buckets — temporary, revoked immediately after genesis (Phase 9) |
| `recovery-pin-capture` | `ra-genesis-pincapture` → `ra-genesis-pincapture@emg-ra-genesis-signer-4185f50f.iam.gserviceaccount.com` | `raGenesisKmsPinCapture` (get + viewPublicKey only, no useToSign) on the signing key; `raGenesisStorageWriter` on the pin-store bucket only |
| `compromise-ledger-writer` | `ra-genesis-ledgerwriter` → `ra-genesis-ledgerwriter@emg-ra-genesis-ledger-7161f246.iam.gserviceaccount.com` | `raGenesisStorageWriter` on the ledger bucket only — no KMS grant of any kind, no pin-store access |

No qualification GSA ever held a project-level role of any kind (confirmed via `gcloud projects get-iam-policy` returning zero bindings for any of the 6 GSAs) and none ever had a user-managed key (confirmed via `gcloud iam service-accounts keys list --managed-by=user` returning empty for all 6).

## Contents

- `IAM_PROOF.md` — Phase 2 negative IAM proofs (domain-separation boundaries, live-tested and structurally verified)
- `PRE_GENESIS_STATE.md` — Phase 3 precondition evidence
- `DUAL_CONTROL.md` — Phase 4 positive + 3 negative dual-control tests
- `GENESIS_RESULT.md` — Phase 5 the single real genesis execution
- `POST_GENESIS_VERIFICATION.md` — Phase 6 independent verification against real provider state
- `IDEMPOTENCY.md` — Phase 7 rerun proof
- `FAIL_CLOSED_MATRIX.md` — Phase 8, including the real KMS-disable propagation-timing finding
- `BOOTSTRAP_REVOCATION.md` — Phase 9
- `ATTACK_MATRIX.md` — Phase 10 consolidated self-falsification results
- `CLEANUP.md` — Phase 11
- `LIMITATIONS.md`
- `real_genesis_evidence.json`, `final_authority_head.json`, `final_transition_history.json`, `witness_bucket_listing_with_retention.txt`, `trackf_key_disabled_state.json` — raw sanitized evidence
- `SHA256SUMS.txt`

## Summary

- **One, and exactly one, real genesis operation completed**: real dual control, real Spanner Commit (`UNAMBIGUOUS_SUCCESS`), real Cloud KMS `AsymmetricSign` via the real authenticated TLS signerrpc path, real immutable GCS witness write (`CREATE_SUCCESS`), real durable bootstrap evidence with an independently-verified self-hash.
- **revision = 1, predecessor revision = 0, predecessor digest = zero-Digest32 sentinel** — confirmed by direct, independent Spanner and GCS queries, not merely the orchestrator's own self-report.
- **Idempotent rerun** confirmed via unchanged provider-side state (same GCS object generation, same row counts) — zero second commit, zero second signing operation.
- **Full fail-closed matrix** (11 distinct negative scenarios) all correctly refused genesis before any unintended state mutation, including one genuinely emergent finding: real Cloud KMS crypto-key-version DISABLE state exhibits measurable propagation delay (a sign succeeded ~1 minute after disable; the same key correctly refused signing ~5 minutes after disable), which the architecture correctly classified as `OutcomeUnresolved` (`NEW_EPOCH_REQUIRED`-equivalent) rather than a false success.
- **Bootstrap privilege revoked** and empirically confirmed unusable by a fresh credential/pod; ordinary `recovery-authority-runtime` remained fully functional throughout.
- No P0/P1 defect found. No existing `emg-staging` workload touched. No static credential anywhere. No project-level Owner/Editor granted to any qualification principal.
