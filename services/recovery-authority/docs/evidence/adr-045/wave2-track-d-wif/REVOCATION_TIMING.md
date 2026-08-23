# Track D — Revocation / Propagation Timing (sanitized, no token values)

**Binding removed:** `roles/iam.workloadIdentityUser` for `serviceAccount:emg-platform-staging.svc.id.goog[ra-wif-qual/ra-authority-qual]` on `ra-authority-wifqual@emg-platform-staging.iam.gserviceaccount.com`, at `2026-08-23T00:08:12Z` (via `gcloud iam service-accounts remove-iam-policy-binding`).

| Time | Elapsed since removal | Event |
|---|---|---|
| `2026-08-23T00:08:12Z` | 0s | `remove-iam-policy-binding` call completes |
| `2026-08-23T00:08:43Z` | +31s | **Fresh pod**, newly created after removal, still obtains a valid access token correctly scoped to `ra-authority-wifqual@...` (confirmed via `oauth2/v3/tokeninfo`) |
| ~`2026-08-23T00:09:36Z`–`00:09:41Z` (bounded) | ~+84–89s | **Fresh pod** (new, separate) denied on its first token-fetch attempt: `403 Forbidden: Permission 'iam.serviceAccounts.getAccessToken' denied` |

**Conclusion:** binding removal converged somewhere in the window **(31s, ~89s]** after the API call returned success — i.e., propagation took under two minutes in this trial, consistent with (faster than) Google's own general IAM-propagation guidance (commonly documented as up to several minutes). This is **not instantaneous**: a fresh credential-acquisition attempt shortly after revocation can still succeed. This finding is reported honestly, not rounded down to "instant."

**Already-issued token behavior:** an access token obtained *before* the binding was removed (confirmed valid via `tokeninfo` immediately before removal) was re-checked via `tokeninfo` *after* removal and **remained fully valid**, with its `expires_in` counting down normally from its original ~3600s lifetime. GCP access tokens are not subject to real-time revocation-list checking against the WIF/IAM binding on every API call; an already-minted token remains valid until its own natural expiry regardless of the IAM binding being removed afterward. This is standard OAuth2 bearer-token behavior, not a defect, and is reported here exactly as observed rather than assumed.

**No raw token value appears anywhere in this evidence package.** Only token metadata (length, `expires_in`, `scope`, `email`, timestamps) was ever recorded.
