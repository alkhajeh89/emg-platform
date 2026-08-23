# Phase 6 — Independent Post-Genesis Verification

None of the checks below trust the orchestrator's own self-reported `RESULT`/evidence JSON — each is a fresh, independent query against real provider state.

## 1. Spanner contains exactly the expected genesis state

Direct `gcloud spanner databases execute-sql` query against `authority_head`:

```
environment_id=track-f-genesis-qual  resource_incarnation_id=01a030b9-...  authority_epoch=01a030b9-...
revision_number=1  operation_id=01a030b9-...
state_digest=d91907451f353db81e345b656f23562c84cb64a1c820441ebfa44ea8bb9abc96
predecessor_checkpoint_digest=0000000000000000000000000000000000000000000000000000000000000000
commit_timestamp=2026-08-23T22:30:47.885553Z
```

Matches the evidence file's `state_digest_hex` exactly.

## 2. Transition history is consistent

`authority_transition_history` contains exactly one row: `revision_number=1, predecessor_revision=0`, same `commit_timestamp`, same digest.

## 3. GCS witness bytes match the accepted committed payload

Direct `gsutil cat` of the real witness object:

```json
{"environment_id":"track-f-genesis-qual","authority_epoch":"01a030b9-...","resource_incarnation":"01a030b9-...",
 "operation_id":"01a030b9-...","revision_number":1,"predecessor_revision":0,
 "predecessor_digest_hex":"0000...0000","state_digest_hex":"d91907451f...","commit_timestamp":"2026-08-23T22:30:47.885553Z",
 "writer_signature_hex":"304402200d0f94ca9dedde3753e921a6c5e8fca58c14361b424c3c4471a9c72f3130f75202206f20b86a6b840da93168a6fa8825a3592367d5b6a656179a9c6d55cce63c34d8",
 "signing_key_id":"projects/emg-ra-genesis-signer-4185f50f/.../cryptoKeyVersions/1"}
```

`writer_signature_hex` is a genuine 70-byte DER-encoded ECDSA signature (`0x3044...` SEQUENCE header, consistent with P-256). `state_digest_hex`, `commit_timestamp`, `signing_key_id` all match the Spanner row exactly.

## 4. Witness object is immutable

`gsutil ls -L` on the object shows `Retention Expiration: Mon, 24 Aug 2026 22:30:48 GMT` — real Bucket Lock retention applied to this specific object, inherited from the bucket's locked 1-day policy. The object cannot be deleted or overwritten before that time by any principal, including the bucket's own project owner.

## 5. Pin remains byte/fingerprint consistent

Re-read via `keypinning.Store.Get` immediately after capture: `fingerprint=ede06828609e9451bed9e40fd851e5affd4d96ff6c70cba936836710f582ea29`, matching the captured value exactly.

## 6. Compromise ledger remains authoritative

Ledger bucket contained zero records at genesis time → `StatusNotDistrusted` was the real, correctly-evaluated default (not a hardcoded bypass) — confirmed later in `FAIL_CLOSED_MATRIX.md` by declaring a real distrust record and observing genesis correctly refuse.

## 7. Evidence self-hash verifies

An independent Go program (`trackfverifyevidence`, never committed) that never calls any unexported `bootstrap` function, instead re-implementing the exact canonical-string + SHA-256 + base64 algorithm read directly from `evidence.go`'s source, recomputed the digest from the evidence JSON's own field values:

```
stored=OxuYZAvqF2792zeoXrrjanyf45RrrV/X3T4teBIKtaU=
recomputed=OxuYZAvqF2792zeoXrrjanyf45RrrV/X3T4teBIKtaU=
match=true
```

## 8. No second commit occurred

`SELECT COUNT(*) FROM authority_head` / `authority_transition_history` for this `(environment_id, resource_incarnation_id)` = exactly 1 row each, both immediately after genesis and again after the Phase 7 idempotent rerun.

## 9. No alternate signing key/version was accepted

The witness object's `signing_key_id` matches exactly the one requested and pinned key version — no other version was ever pinned or could have been substituted (pin-store contains exactly one pin, for exactly this key version).
