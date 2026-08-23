# Phase 3 — Pre-Genesis State

All captured via direct, independent queries against real provider state before the real genesis attempt.

| Precondition | Result |
|---|---|
| Spanner `authority_head` has no existing genesis | `row_count = 0` |
| Spanner `authority_transition_history` has no Track-F genesis | `row_count = 0` |
| Witness key does not exist | Witness bucket listing: empty |
| Correct KMS version is ENABLED | `gcloud kms keys versions describe 1 ... → state: ENABLED` |
| Public key captured into the immutable pin store | Real `keypinning.CaptureFromKMS` + `keypinning.NewGCSStore.Pin` run via the `ra-genesis-pincapture` identity: `fingerprint=ede06828609e9451bed9e40fd851e5affd4d96ff6c70cba936836710f582ea29`, independently re-read immediately after write, confirmed matching (`match=true`) |
| Compromise ledger evaluates the signing subject as not distrusted | Ledger bucket empty at this point → default `StatusNotDistrusted` |
| TLS certificate validates correctly | Deferred to, and confirmed by, the real genesis run itself (Phase 5) via the same TLS-trust construction as production (`newSignerHTTPClient`-equivalent) |
| WIF identities resolve to expected principals | `ra-genesis-authority` pod's metadata identity → `ra-genesis-authority@emg-platform-staging.iam.gserviceaccount.com`; `ra-genesis-signer` pod's metadata identity → `ra-genesis-signer@emg-ra-genesis-signer-4185f50f.iam.gserviceaccount.com` — both confirmed via the real GKE metadata server |
| Bootstrap identity is temporary/revocable | `recovery-bootstrap-deployment`'s `standing_grant: false` (per `provisioning/contract.json`); empirically confirmed revocable in Phase 9 |

No precondition was weakened or skipped to make genesis run.
