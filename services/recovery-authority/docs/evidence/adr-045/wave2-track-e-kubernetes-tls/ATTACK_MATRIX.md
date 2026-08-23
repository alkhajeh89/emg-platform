# Consolidated Attack Matrix (Phase 12)

Every security ambiguity below was resolved by failing closed.

| Attack | Result | Evidence |
|---|---|---|
| Unrelated pod reaches signer | **Denied** | `NETWORKPOLICY_MATRIX.md` B |
| Wrong namespace reaches signer | Denied (structural, not independently re-tested — see `NETWORKPOLICY_MATRIX.md` D) | — |
| Right labels / wrong KSA attempts signer | **Network-allowed, application-denied** — correctly layered, not conflated | `NETWORKPOLICY_MATRIX.md` C, `SIGNERRPC_AUTH_MATRIX.md` |
| No token over valid TLS | **Denied** (401) | `SIGNERRPC_AUTH_MATRIX.md` |
| Wrong-audience token | **Denied** (403) | `SIGNERRPC_AUTH_MATRIX.md` |
| Authority tries plaintext | **Denied** (400, no TLS fallback) | `TLS_MATRIX.md` G |
| MITM / self-signed cert | **Denied** (unknown authority) | `TLS_MATRIX.md` H |
| Wrong SAN | **Denied** | `TLS_MATRIX.md` I |
| Authority attempts direct KMS access | Structurally denied — authority GSA holds zero KMS grants anywhere (by construction, mirroring Track D); not re-tested live this wave since it is identical ground to Track D's already-qualified negative IAM matrix | Track D evidence |
| Signer attempts Spanner/GCS access | Structurally denied — signer GSA holds zero Spanner/GCS grants anywhere; not re-tested live this wave for the same reason | Track D evidence |
| Authority reads signer TLS Secret | **Denied** — no Kubernetes API access at all (no RBAC binding, no automounted token) | `POD_SECURITY.md` |
| Signer reads authority-only config/secret | Signer's only mounted Secret is its own TLS material; it never references or mounts anything authority-specific | Manifest review, `test_recovery_authority_does_not_mount_signer_tls_secret` (inverse direction) |
| Public exposure via Service/Ingress/NodePort | **None exists** — `ClusterIP` only, no `Ingress`, no `LoadBalancer`, no `NodePort` | `NETWORKPOLICY_MATRIX.md` I/J |
| NetworkPolicy deletion simulation | Not performed — the diagnostic matrix already required temporarily replacing the DNS-egress rule under explicit, narrowly-scoped authorization; a further "delete and restore" simulation was judged redundant given the equivalent risk/coverage already exercised, and was not separately authorized |
| Pod relabeling | Covered by the wrong-identity test (`SIGNERRPC_AUTH_MATRIX.md`): a pod carrying the authority's exact labels but a different KSA was correctly denied at the application layer |
| KSA identity confusion | **Denied** — signer's own identity used as a caller was rejected by the allow-list (`SIGNERRPC_AUTH_MATRIX.md`) |
| Certificate rotation | Documented — requires restart, not live-reloaded (`RESTART_FAILURE.md`) |
| Signer unavailable | **Fails closed with a bounded timeout**, no insecure fallback (`RESTART_FAILURE.md`) |
| Metadata/WIF unavailable | Not independently simulated this wave (would require degrading the real GKE metadata server, out of safe scope); the default-KSA test (`SIGNERRPC_AUTH_MATRIX.md`) demonstrates the adjacent case of an identity the metadata server cannot mint a usable token for |
| Already-issued token after WIF revocation | Already exhaustively, empirically qualified in Wave 2 Track D (`REVOCATION_TIMING.md`) — not re-run here to avoid redundant infrastructure churn; the underlying mechanism (GKE WIF token issuance) is identical and unchanged |

`spec.serviceAccountName`'s immutability on a running Pod (preventing a live pod from changing its own KSA association) is a structural Kubernetes API-server guarantee, not empirically re-tested here, consistent with Track D's own treatment of the identical structural fact.
