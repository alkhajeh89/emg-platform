# Phase 5 — The Single Real Genesis Execution

Executed via a diagnostic-only Go orchestrator built from the real, unmodified `bootstrap`, `spannercommit`, `gcswitness`, `keypinning`, `compromiseledger`, and `signerrpc` packages (a local `replace` directive into a disposable build context — never committed to the repository), running under the real, temporary `recovery-bootstrap-deployment` WIF identity.

## Request

| Field | Value |
|---|---|
| `environment_id` | `track-f-genesis-qual` |
| `resource_incarnation_id` | `01a030b9-0363-7101-8791-b85e1bb8234e` (real UUIDv7) |
| `authority_epoch` | `01a030b9-0363-70ee-81ef-7c1064c78c1b` (real UUIDv7, via `bootstrap.GenerateFreshIdentifiers`) |
| `operation_id` | `01a030b9-0363-70f2-a5dc-9f55949b5a7c` (real UUIDv7) |
| `spanner_database` | `projects/emg-platform-staging/instances/ra-genesis-qual/databases/authority` |
| `signing_key_id` | `projects/emg-ra-genesis-signer-4185f50f/locations/me-central1/keyRings/ra-genesis-ring/cryptoKeys/ra-genesis-key/cryptoKeyVersions/1` |
| Request digest | `7bec56eba62832b189c5a3b859341d452ccc4994382929c74fae2aceb169271b` |
| Witness key | `genesis/track-f-genesis-qual/01a030b9-0363-7101-8791-b85e1bb8234e/01a030b9-0363-70ee-81ef-7c1064c78c1b/1.json` |

## Result

```
RESULT {"outcome":"COMPLETED"}
```

| Field | Value |
|---|---|
| Commit classification | `UNAMBIGUOUS_SUCCESS` |
| Witness create outcome | `CREATE_SUCCESS` |
| Final epoch state | `ACTIVE` |
| State digest | `d91907451f353db81e345b656f23562c84cb64a1c820441ebfa44ea8bb9abc96` |
| Real Spanner commit timestamp | `2026-08-23T22:30:47.885553Z` |
| Resulting revision | `1` |
| Predecessor revision | `0` |
| Predecessor digest | `0000000000000000000000000000000000000000000000000000000000000000` (zero-Digest32 sentinel — exact match) |
| Evidence self-hash | `OxuYZAvqF2792zeoXrrjanyf45RrrV/X3T4teBIKtaU=` |

Full evidence file: `real_genesis_evidence.json`.

Invariant confirmation: `revision = 1`, `predecessor revision = 0`, `predecessor digest = zero-Digest32 sentinel` — exactly as required. V2 COMMITTED construction and `DomainNewEpochGenesis` were used via the real, unmodified `rotationcommit.CompleteGenesisCommit`/`protocol.HashCanonical` code path — never fabricated, never manually inserted, never separately manufactured.
