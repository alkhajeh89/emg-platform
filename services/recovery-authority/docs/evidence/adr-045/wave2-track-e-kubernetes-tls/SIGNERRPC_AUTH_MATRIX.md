# Real signerrpc Application Authentication Over TLS (Phase 7)

All calls made over the real TLS transport already qualified in `TLS_MATRIX.md`, using real, WIF-issued Google-signed OIDC ID tokens (never a static credential).

## Authorized caller

| Caller identity | Result |
|---|---|
| `ra-authority-k8squal@emg-platform-staging.iam.gserviceaccount.com` (via `ra-authority-k8squal` KSA, real WIF token, correct audience) | **Accepted** — `ActiveKeyID` and `SignCommittedDigest` both succeeded, producing a genuine Cloud KMS signature |

## Unauthorized callers — all denied before any signing operation

| Caller / condition | Mechanism | Result |
|---|---|---|
| No bearer token | Raw HTTPS request, `Authorization` header omitted | Real `HTTP/1.1 401 Unauthorized` (`ErrMissingBearerToken`) |
| Malformed bearer token | `Authorization: Bearer not-a-real-jwt` | Real `HTTP/1.1 403 Forbidden` (`ErrCallerNotAuthorized`) |
| Wrong audience | Real WIF token minted for `https://wrong-audience.example:8443` instead of the signer's real audience | TLS handshake succeeded (transport is fine); real `403`: `signerrpc: caller identity is not authorized to invoke the signing service` — rejected by `idtoken.Validate`'s audience check |
| Default (unannotated) KSA | Pod using the namespace's plain `default` KSA, no `iam.gke.io/gcp-service-account` annotation | Denied **even earlier** than the server: `idtoken.NewTokenSource` itself failed — the GCE metadata server has no identity-token endpoint defined for an unmapped KSA (`GCE metadata "instance/service-accounts/default/identity?..." not defined`) |
| Wrong identity (signer's own GSA, right namespace, right network labels) | Pod using `ra-signer-k8squal` KSA but the authority's own NetworkPolicy-matching labels | TLS handshake succeeded, real WIF token minted successfully (signer's own identity is valid WIF-wise) — but real `403`: rejected by the server's `RECOVERY_SIGNER_ALLOWED_CALLER_EMAILS` allow-list check. **This is the load-bearing proof that NetworkPolicy label-matching and application-layer identity authentication are two independent gates**: the pod reached the signer over the network (matching `app.kubernetes.io/name: ra-authority-k8squal` satisfied the NetworkPolicy selector) but was still correctly denied by signerrpc's own authentication layer. NetworkPolicy is never treated as proof of caller identity in this qualification. |

No raw JWT, access token, or bearer token value appears anywhere in this evidence package — only outcomes, status codes, and error classifications.
