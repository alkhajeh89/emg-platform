# Phase 4 — Dual Control

## Positive (used for the real genesis in `GENESIS_RESULT.md`)

Two structurally valid, independent `bootstrap.Approval` records:

| Role | Approver | Bound to |
|---|---|---|
| `AUTHORITY` | `authority-approver@emg-governance.example` | The real `RequestDigest()` computed from this exact `GenesisRequest`'s fields |
| `SIGNING` | `signing-approver@emg-governance.example` | Same digest |

Both fresh (well within the 72h freshness window), both distinct approvers, both bound to the identical request digest — `bootstrap.NewGenesisRequest` accepted them and genesis proceeded.

## Negative (run before the real execution; all fail via `NewGenesisRequest` itself, before any Spanner/GCS/KMS call is ever attempted — zero mutation of real state)

| # | Test | Result |
|---|---|---|
| 1 | Single approval only (AUTHORITY, no SIGNING) | `REQUEST_REJECTED`: `"dual control requires exactly one AUTHORITY approval and one SIGNING approval"` |
| 2 | Same approver for both roles | `REQUEST_REJECTED`: `"AUTHORITY and SIGNING approvals must come from distinct approvers"` |
| 3 | Altered/mismatched approval digest (simulating a GenesisRequest altered after approval) | `REQUEST_REJECTED`: `"approval RequestDigest does not match this exact genesis request"` |
| — | Stale approval (>72h old) — run later, in the Phase 8 fail-closed matrix for organizational grouping | `REQUEST_REJECTED`: `"approval is older than the maximum permitted age"` |

Each of these three (plus the stale-approval case in `FAIL_CLOSED_MATRIX.md`) was confirmed to occur before dependency construction — the program's own control flow computes and validates `NewGenesisRequest` before ever constructing a Spanner, GCS, or signer client.
