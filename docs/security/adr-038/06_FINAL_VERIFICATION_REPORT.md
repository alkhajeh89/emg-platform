# ADR-038 Capability Verification — Final Report

**Scope reminder:** this is the mandatory non-production capability
verification gate required by ADR-038 Ch. VI §6.5 / Ch. XIII §13.3 / Ch. XV
§15.1 before Phase 2B implementation may begin. ADR-038's architecture is
Accepted and authoritative and was not reopened. This report does not
authorize, and is not, Phase 2B implementation.

## Summary

All 10 mandatory EMG Delegation Profile properties (ADR-038 §6.3 / Chapter
XV AC-1 through AC-11) were demonstrated with real, executable evidence
against a real Keycloak 25.0 instance, in a fully isolated non-production
environment, using synthetic test identities only. **25 of 25 tests pass**
— 10 positive, 11 negative/fail-closed, 3 credential-lifetime, 1
audit-attribution integration. No mandatory property required a workaround
that weakened an ADR-038 invariant; none could not be satisfied.

Full detail: `03_CAPABILITY_MATRIX.md` (per-property evidence),
`02_KEYCLOAK_VERIFICATION_CONFIG.md` (experimental Keycloak findings),
`05_TEST_EXECUTION_LOG.md` (exact commands and output).

## Files changed

New files only — nothing existing was modified.

```
docs/security/adr-038/00_REPOSITORY_BASELINE.md
docs/security/adr-038/01_TEST_ENVIRONMENT_SPEC.md
docs/security/adr-038/02_KEYCLOAK_VERIFICATION_CONFIG.md
docs/security/adr-038/03_CAPABILITY_MATRIX.md
docs/security/adr-038/04_FINDINGS_AND_EXTERNAL_CONCERNS.md
docs/security/adr-038/05_TEST_EXECUTION_LOG.md
docs/security/adr-038/06_FINAL_VERIFICATION_REPORT.md   (this file)

tests/security/adr_038/README.md
tests/security/adr_038/docker-compose.verification.yml
tests/security/adr_038/realm/emg-verification-realm.json
tests/security/adr_038/generate_env.sh
tests/security/adr_038/provision.py
tests/security/adr_038/keycloak_client.py
tests/security/adr_038/claim_adapter.py
tests/security/adr_038/downstream_validator.py
tests/security/adr_038/audit_harness.py
tests/security/adr_038/conftest.py
tests/security/adr_038/test_positive_delegation.py
tests/security/adr_038/test_negative_delegation.py
tests/security/adr_038/test_credential_lifetime.py
tests/security/adr_038/test_audit_attribution.py
tests/security/adr_038/.gitignore
```

Explicitly NOT changed: `tools/seed-data/keycloak/emg-realm.json`,
`docker/keycloak/import/emg-realm.json`, `docker-compose.yml`, any
`services/*` production source, ADR-035, ADR-036, ADR-038. No new ADR was
created. `.env.verification.local` exists on disk (throwaway generated
secrets) but is gitignored and untracked — never committed.

## Exact verification topology

Isolated Docker Compose project `emg-adr038-verification`: one container,
`emg-adr038-verification-keycloak` (Keycloak 25.0, `start-dev --import-realm
--features=token-exchange,admin-fine-grained-authz`), network
`emg-adr038-verification-net`, port `8180`, realm `emg-verification`. Six
clients (`emg-verification-ropc`, `emg-verification-bff`,
`emg-verification-bff-unauthorized`, `emg-verification-audience-a`,
`emg-verification-audience-b`, `emg-svc-knowledge-graph-writer`), two human
test users (`human-principal-a` / CONFIDENTIAL/tenant-a,
`human-principal-b` / INTERNAL/tenant-b). Full detail:
`01_TEST_ENVIRONMENT_SPEC.md`.

## Verdict

**VERIFIED WITH REQUIRED CONFIGURATION**

Keycloak 25.0 supports the complete EMG Delegation Profile — every one of
the 10 mandatory properties was demonstrated with real, positive AND
negative executable evidence, and no invariant needed to be weakened to get
there. It is not an unconditional **VERIFIED**, because getting there
required specific, named, non-default configuration this verification had
to discover and apply — configuration that Phase 2B's production
implementation must apply again, deliberately, rather than assume:

## Remaining production-only configuration requirements

These are ordinary Phase 2B implementation/deployment decisions this
verification deliberately left out of scope (per its own mandate — it
verifies *capability*, not production configuration), surfaced here so they
are not rediscovered the hard way in production:

1. **`sub`-claim projection mapper on every downstream audience client.**
   Not on by default (`02_KEYCLOAK_VERIFICATION_CONFIG.md` Finding 2).
   Without it, AC-2 (Human Subject Preservation) silently fails for that
   audience specifically — the exchange still succeeds, the credential is
   just missing the one claim everything downstream depends on. This is the
   single highest-risk configuration omission this verification found: it
   fails silently, not loudly.
2. **Fine-grained token-exchange permissions must be explicitly granted per
   Acting Service × per downstream audience**, on both legs (Finding 3).
   There is no platform-wide "delegation enabled" switch; each production
   audience (Knowledge Graph, Audit, Identity, any future service) needs
   its own explicit grant to the production BFF client, and to no one else.
3. **A production BFF/Acting-Service client identity must be added to each
   downstream service's own `_RECOGNIZED_CLIENTS`-equivalent allowlist**
   (confirmed empty of any such entry today — `04_FINDINGS_AND_EXTERNAL_CONCERNS.md`
   finding 4). This is a reviewed source change in each service, exactly
   like the four existing entries, not a configuration file.
4. **Production Delegated Credential lifetime is an undetermined,
   deployment-specific Security Baseline decision.** This verification used
   60s for test-cycle speed and explicitly declines to recommend a
   production number (`test_credential_lifetime.py`'s own docstring, per
   the mission's explicit instruction not to invent a platform-wide
   figure). ADR-038 §7.5 requires only "bounded" and "as short as
   operationally practical."
5. **The two divergent Keycloak realm artifacts
   (`tools/seed-data/keycloak/emg-realm.json` vs
   `docker/keycloak/import/emg-realm.json`) must be reconciled before any
   real BFF client is provisioned** — ADR-035's own already-recorded
   negative consequence, restated here because Phase 2B is the point at
   which it becomes load-bearing rather than theoretical. In particular the
   `emg-frontend` public client in the docker-import artifact must not
   become the production OIDC client — ADR-035 D-3 requires confidential.
6. **Authorization Authority (Keycloak) signing-key custody/rotation
   remains ungoverned by any ADR** (external Concern A, unchanged by this
   verification — see `04_FINDINGS_AND_EXTERNAL_CONCERNS.md`). Not a
   capability-verification failure — nothing tested here depends on key
   rotation cadence — but a real production-readiness item worth resolving
   before Phase 2B ships, tracked here for continuity rather than
   re-litigated.

None of the above required weakening any ADR-038 invariant during this
verification, and none of them block *this* verification's VERIFIED WITH
REQUIRED CONFIGURATION verdict — they are exactly the "named configuration
controls that must be applied during production implementation" the
verdict definition anticipates.
