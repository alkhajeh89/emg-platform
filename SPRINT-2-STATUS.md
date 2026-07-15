# Sprint 2 — Identity Platform — Completion Report

**Branch:** `feature/sprint-2-identity` (off `develop`, per the stated
workflow: `main` protected ← `develop` ← `feature/sprint-2-identity`).
**Epic:** EPIC-02 Identity. **Features:** FEAT-02-1 (Identity Provider
Integration), FEAT-02-2 (Authentication Session Management). **Story:**
US-02. Governing architecture: Module 4 — Identity & Authentication,
ADR-013 (referenced by the Engineering Master Plan; no standalone Module 4
or ADR-013 document was provided to this repository — see "Assumptions"
below).

Scope is exactly Sprint 2 per Engineering Backlog v1.0 §6: FEAT-02-3
(Service Identity & M2M Auth) and FEAT-02-4 (Identity Federation Readiness)
are Sprint 3 and are **not** implemented here.

## 1. What Was Built

| Component | Path | Feature |
| --- | --- | --- |
| Keycloak realm/client seed | `tools/seed-data/keycloak/emg-realm.json` | FEAT-02-1 |
| Keycloak OIDC token client | `services/identity/src/emg_identity/keycloak_client.py` | FEAT-02-1 |
| EMG session issuance/refresh/verify (JWT) | `services/identity/src/emg_identity/session.py` | FEAT-02-2 |
| Concrete `AuthClient` (Sprint 1 shipped only the Protocol) | `services/identity/src/emg_identity/auth_client.py` | FEAT-02-1/02-2 |
| Interim auth-event logging (stand-in for FEAT-04-1) | `services/identity/src/emg_identity/audit.py` | US-02 AC |
| HTTP surface (`/auth/login`, `/auth/refresh`, `/auth/session`, `/healthz`) | `services/identity/src/emg_identity/routers/auth.py`, `main.py` | FEAT-02-1/02-2 |
| Config, dependency wiring, schemas | `services/identity/src/emg_identity/{config,dependencies,schemas}.py` | — |
| Dockerfile + per-service CI | `services/identity/Dockerfile`, `.github/workflows/service-identity.yml` | FEAT-01-4 (wiring) |
| `docker-compose.yml` `identity` service | `docker-compose.yml` | FEAT-01-3 (wiring) |
| Unit tests (22) | `services/identity/tests/` | Deliverable 2 |
| Docs | `services/identity/README.md`, `service.yaml`, root `README.md`, `CHANGELOG.md`, `services/README.md`, `tools/seed-data/README.md` | Deliverable 3 |

## 2. US-02 Acceptance Criteria — Verification

Per Engineering Backlog v1.0 §4:

| Criterion | Status | Evidence |
| --- | --- | --- |
| Keycloak realm and client are provisioned | Met | `tools/seed-data/keycloak/emg-realm.json`: realm `emg`, confidential client `emg-identity-service` (Direct Access Grants), 2 seed users. Imported automatically by `docker-compose.yml`'s `keycloak` service. |
| Login issues a valid session token | Met | `POST /auth/login` → Keycloak password grant → EMG-minted access+refresh JWT pair (`session.py`). Verified in `test_auth_router.py::test_login_success_returns_token_pair`. |
| Token carries the claims Module 5's PEP requires | Met (by design, see §3) | Access token embeds `sub`, `roles`, `attributes` — the exact shape of `emg_auth_client.Principal`, matching Sprint 1's PEP-facing contract. `attributes` carries `classification_clearance`/`department` from Keycloak's custom claims. |
| Failed authentication is logged via the audit pipeline (FEAT-04-1) | Met, with a documented interim (FEAT-04-1 doesn't exist until Sprint 5-6) | `StructuredLogAuditSink` emits via `emg_telemetry` (ADR-015 shared schema) on every login/refresh denial. Verified in `test_auth_router.py::test_login_failure_returns_401_and_logs_denial` and `test_refresh_invalid_token_returns_401_and_logs`. See §3 and `services/identity/README.md` "Known Limitations" for the swap-in plan once FEAT-04-1 lands. |

## 3. Design Decisions & Assumptions (documented, not silent)

No standalone Module 4 or ADR-013 document was available in this
repository's `docs/architecture/` reference set (only ADR-014/015/016/017
and the two program-level documents were provided in Sprint 1). Per
Engineering Master Plan §1, "where architecture leaves an implementation
detail open, [engineering] leaves it open too — it is refined during sprint
backlog grooming." The following Sprint 2 decisions fill exactly that kind
of gap, refining detail rather than redesigning anything Module 4 or ADR-013
are known to specify from the Backlog/Master Plan text:

1. **EMG mints its own session token rather than forwarding Keycloak's**, so
   every downstream service depends on one EMG-governed contract. Full
   rationale in `services/identity/README.md` §"Design Decisions."
2. **Stateless JWT sessions, no session database** — avoids schema debt
   ahead of Module 6 (Sprint 5-6). Refresh tokens rotate on every use.
3. **User federation (LDAP/AD) is not configured** in the local-dev realm —
   real federation is environment-specific and out of scope for a seed file.
4. **No session/refresh-token revocation** — acceptable given US-02's stated
   acceptance criteria (issuance, refresh, expiry — not revocation) and the
   short refresh TTL (12h default).

These are implementation refinements within the frozen baseline, not new
architecture: no ADR was created, no module was redefined, and the identity
service still authenticates only — it makes no authorization decision
(Module 5 territory) and writes no audit record (Module 6 territory).

## 4. Defect Found and Fixed in Sprint 1 Code

While wiring FEAT-02-1's failed-login logging through `emg_telemetry`
(Sprint 1, `libs/python/emg-telemetry`), every call to
`get_logger(...).warning(..., extra={"module": ...})` raised
`KeyError: Attempt to overwrite 'module' in LogRecord` — `module` is a
reserved `logging.LogRecord` attribute, and passing it via `extra=` always
raises, in any Python logging usage, regardless of caller. This is a
pre-existing defect in Sprint 1's `emg-telemetry` package (its own test
carried the same `extra={"module": ...}` shape and would fail identically
under a clean interpreter/bytecode cache).

**Why fixed here rather than deferred:** Sprint 2's US-02 acceptance
criterion ("failed authentication is logged") cannot be met while the
logger itself crashes on the ADR-015 schema's own `module` field — leaving
it broken would mean shipping Sprint 2 without a working audit-log stand-in,
silently failing the acceptance criterion it depends on.

**Fix (`libs/python/emg-telemetry/src/emg_telemetry/logger.py`):** the
public ADR-015 schema (`actor`, `module`, `action`, `outcome`) is unchanged
in both the `extra=` calling convention and the emitted JSON; internally,
`get_logger()` now returns a `LoggerAdapter` that remaps these four names to
collision-safe attribute names (`emg_actor`, `emg_module`, `emg_action`,
`emg_outcome`) before the stdlib `Logger` ever sees them. No caller-visible
behavior changed except that calls which previously always raised now
succeed. A regression test was added
(`test_logger_extra_keys_do_not_collide_with_logrecord_reserved_names`).

This is a bug fix in shared tooling, not a redesign of Module 3 or any
architecture: the ADR-015 §1 schema (actor/module/action/outcome/timestamp/
correlation-id) is preserved exactly; only the internal, non-public
implementation changed.

## 5. Verification Performed

1. **Unit tests:** `pytest libs services` — **37/37 passed** (15 pre-existing
   from Sprint 1's `/libs` + 22 new in `services/identity`, including 1
   Sprint 1 regression test).
2. **Lint:** `ruff check libs services` — **all checks passed**.
3. **Type checking:** `mypy --strict` against all 26 source files across
   `/libs` and `services/identity/src` — **no issues found**.
4. **YAML validity:** `yamllint` against `docker-compose.yml` and the new
   `.github/workflows/service-identity.yml` — **no errors**.
5. **Structural checks:** `docker-compose.yml` parsed and confirmed to
   include the new `identity` service alongside the 5 Sprint 1 services;
   `service-identity.yml` confirmed to reference the Sprint 1 reusable
   template with the correct `service-path`/`language` inputs.
6. **App smoke test:** `create_app()` imports and constructs successfully
   with the `/auth` router mounted.

## 6. Known Limitations (carried into Sprint 3 planning)

- No live GitHub repository in this environment — `.github/workflows/service-identity.yml` was validated structurally (YAML + reference correctness), not run on an actual Actions runner. Same caveat as Sprint 1's `SPRINT-1-STATUS.md`.
- No live Keycloak instance was exercised — `KeycloakClient` was tested against a mocked `httpx` transport (`test_keycloak_client.py`), not a running Keycloak container, since this environment has no Docker daemon (same limitation noted in Sprint 1).
- Session revocation, LDAP/AD federation, and M2M auth are explicitly out of Sprint 2 scope (see §3) and are not silently missing — they are FEAT-02-3/02-4 (Sprint 3) or later.

## 7. Suggested Git Commit Message

```
feat(sprint-2): implement Identity Platform — EPIC-02 (FEAT-02-1, FEAT-02-2)

Implements Sprint 2 of the Engineering Backlog v1.0 exactly: Identity
Provider Integration (FEAT-02-1) and Authentication Session Management
(FEAT-02-2). US-02 acceptance criteria met.

- services/identity: Keycloak-backed login (Direct Access Grants) against
  the seeded local-dev realm (tools/seed-data/keycloak/emg-realm.json).
- services/identity: EMG-minted, independently-governed session tokens
  (JWT access + rotating refresh), carrying the roles/attributes claims
  Module 5's future PEP will consume.
- SessionAuthClient: concrete emg_auth_client.AuthClient implementation
  (Sprint 1 shipped the Protocol only).
- Interim authentication-event logging via emg_telemetry, standing in for
  the audit pipeline (FEAT-04-1, Sprint 5-6); documented swap-in plan.
- Wired identity into docker-compose.yml and a per-service CI workflow
  using the Sprint 1 reusable pipeline template (FEAT-01-4).
- 22 new unit tests (session issuance/verify/expiry/tamper, Keycloak client
  success/failure, HTTP surface incl. failed-auth log emission).

Fix: libs/python/emg-telemetry's get_logger() crashed with
`KeyError: Attempt to overwrite 'module' in LogRecord` whenever extra=
included the ADR-015 schema's own "module" field (a reserved LogRecord
attribute) — pre-existing Sprint 1 defect, discovered while wiring Sprint
2's failed-login logging and fixed since US-02 depends on it. Public
schema (actor/module/action/outcome) unchanged; internal attribute names
only. Regression test added.

No architecture redesigned, no prior module modified in behavior, no new
ADR created. Scope: EPIC-02 FEAT-02-1/02-2 only — FEAT-02-3 (M2M auth) and
FEAT-02-4 (federation readiness) remain for Sprint 3.

Refs: US-02, TASK-02-1, TASK-02-2, TASK-02-3
```

## 8. Recommendation

Sprint 2 (FEAT-02-1, FEAT-02-2) is complete and verified against every
stated US-02 acceptance criterion. FEAT-02-3 and FEAT-02-4 remain, by
design, for Sprint 3.

**Stopping here for review before proceeding to Sprint 3, per instruction.**
