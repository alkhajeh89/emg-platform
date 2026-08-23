# Phase 10 — Consolidated Attack Matrix / Self-Falsification

Every item below is backed by a real, already-documented test in this evidence package — none is asserted as a structural assumption alone unless explicitly marked.

| Property attacked | Result | Evidence |
|---|---|---|
| Domain separation (authority↔signer↔pin-capture↔ledger-writer) | **Held** — every cross-domain capability attempt was denied with a real provider error | `IAM_PROOF.md` |
| Pinned-key enforcement | **Held** — an unpinned key version was refused (`no pin exists`) | `FAIL_CLOSED_MATRIX.md` #2 |
| Compromise-ledger fail-closed behavior | **Held** — both "ledger unavailable" and "key actually distrusted" refused genesis; ledger unavailability never failed open | `FAIL_CLOSED_MATRIX.md` #4, #11 |
| Dual control | **Held** — single approval, same approver, and mismatched digest all refused; two genuine independent approvals succeeded | `DUAL_CONTROL.md` |
| Single-use genesis | **Held** — idempotent rerun produced zero second commit, zero second witness write, zero second signing operation, proven from real provider state | `IDEMPOTENCY.md` |
| Immutable witness | **Held** — real Bucket Lock retention confirmed on the actual object; a conflicting pre-seeded object was never overwritten | `POST_GENESIS_VERIFICATION.md` #4, `FAIL_CLOSED_MATRIX.md` #8 |
| Signer authentication (TLS + bearer) | **Held** — wrong CA, wrong audience, and an unauthorized principal were all refused; the real, authorized flow succeeded | `FAIL_CLOSED_MATRIX.md` #5–7, `GENESIS_RESULT.md` |
| WIF separation | **Held** — the signer identity could not exercise bootstrap privilege at all (denied at the first witness-precondition read) | `FAIL_CLOSED_MATRIX.md` #7 |
| Bootstrap revocation | **Held** — a fresh credential/pod was denied after revocation; ordinary runtime remained functional | `BOOTSTRAP_REVOCATION.md` |
| Absence of later-read ambiguity resolution | **Held by design and observation** — `handleExistingWitness` cryptographically re-verifies existing witness content against the request's own expected binding rather than trusting its mere presence; the conflict test (#8 above) demonstrates this directly: malformed pre-seeded content was correctly rejected, never silently accepted as if it were the real prior output |

No structural assumption was converted into an empirical PASS claim without a corresponding real test in this package. Two boundaries were explicitly **not** re-tested with a live attack this wave, and are reported as such rather than silently assumed: authority-cannot-sign and signer-cannot-write-Spanner were tested live in Track F itself (`IAM_PROOF.md`); pin-capture-cannot-sign and ledger-writer-cannot-sign were verified structurally (IAM policy inspection) rather than via a live attack, since their IAM policies contain no path to the relevant permission at all — a live attack would necessarily reproduce the identical, already-known-correct denial.
