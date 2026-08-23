# Real TLS Handshake Qualification (Phase 6)

All tests performed with a diagnostic client built from the real, unmodified `internal/authority/signerrpc` and `internal/authority/protocol` packages (via a local `replace` directive into a disposable build context — never committed to the repository), running under the real `ra-authority-k8squal` KSA/WIF identity, using the exact TLS trust construction pattern as `cmd/recovery-authority`'s `newSignerHTTPClient`.

## Positive (A–F)

| # | Test | Result |
|---|---|---|
| A | HTTPS connection succeeds | **Yes** |
| B | Correct CA succeeds | **Yes** — qualification CA trusted via mounted CA bundle |
| C | Correct DNS/SAN succeeds | **Yes** — `emg-recovery-signer.ra-k8s-qual.svc.cluster.local` matches the cert's SAN exactly |
| D | TLS version ≥ 1.2 | **Yes — TLS 1.3 negotiated** (`cipher=0x1301`, TLS_AES_128_GCM_SHA256), exceeding the minimum |
| E | Signer RPC reaches app auth layer | **Yes** — see `SIGNERRPC_AUTH_MATRIX.md` |
| F | signerrpc bearer-auth preserved over TLS | **Yes** |

Captured real handshake evidence (sanitized — no private key, no token):
```
TLS_HANDSHAKE_OK version=TLS1.3 cipher=0x1301 peerCertSubject="CN=emg-recovery-signer.ra-k8s-qual.svc.cluster.local,O=EMG Track E Qualification"
OK ActiveKeyID: projects/emg-ra-signer-k8squal-a970703a/locations/me-central1/keyRings/ra-tracke-ring/cryptoKeys/ra-tracke-key/cryptoKeyVersions/1
OK SignCommittedDigest: keyID=...cryptoKeyVersions/1 sigLen=72 sigHexPrefix=30460221008d57ea
```
`sigLen` (71/72 bytes) is consistent with a genuine DER-encoded ECDSA P-256 signature from a real Cloud KMS `AsymmetricSign` call — not a fake/simulated value.

## Negative (G–N)

| # | Test | Result |
|---|---|---|
| G | Plaintext HTTP fails | **Yes** — `wget http://...:8443/healthz` → real `HTTP/1.0 400 Bad Request` (the TLS-only listener rejects a raw plaintext request; no plaintext fallback exists) |
| H | Wrong CA fails | **Yes** — client trusting only an unrelated, freshly-generated CA against the real (correctly CA-signed) server cert: `x509: certificate signed by unknown authority` |
| I | Wrong server name/SAN fails | **Yes** — server temporarily made to present a cert signed by the *same, correct* CA but with SAN `wrong-host.example`: client (still trusting the correct CA, connecting to the correct hostname) got `x509: certificate is valid for wrong-host.example, not emg-recovery-signer.ra-k8s-qual.svc.cluster.local`. Server's real cert was restored via the real ExternalSecret/GCPSM path immediately afterward (see `RESTART_FAILURE.md`) and the positive path was reconfirmed working. |
| J | Expired/not-yet-valid cert fails | Not separately reproduced this wave — structurally guaranteed by Go's `crypto/tls`/`crypto/x509` `NotBefore`/`NotAfter` validation, the same code path already exercised by every other test in this matrix; reproducing a genuinely expired certificate was judged not to add qualification value proportionate to the added disruption of a second live cert swap |
| K | Missing client CA config (default pool) | Structurally guaranteed to fail since the qualification CA is self-issued and not in any public trust store — not separately re-tested as its own case beyond the CA-trust tests above |
| L | `allowInsecure=false` enforced | **Yes** — `RECOVERY_SIGNER_ALLOW_INSECURE: "false"` and `RECOVERY_AUTHORITY_ALLOW_INSECURE: "false"` in both qualification ConfigMaps, confirmed via the running pods' logs (`"tls": true`) |
| M | Arbitrary self-signed cert fails | Covered by test H (an arbitrary, unrelated CA/cert is rejected identically to any other untrusted chain) |
| N | TLS bypass cannot be enabled via accidental environment defaults | **Yes** — `RECOVERY_SIGNER_ALLOW_INSECURE` and `RECOVERY_AUTHORITY_ALLOW_INSECURE` both require an explicit `"true"` string; absent/misconfigured defaults to secure (`false`), confirmed by source reading of `runtimeconfig.OptionalBool` and by the running configuration |

No bearer token, JWT, OAuth token, or TLS private key was ever logged or committed at any point in this matrix.
