# Seed / Mock Data Fixtures

Per Engineering Master Plan §13 (Development Environment Checklist): "Mock
government data fixtures available for Lab Prototype development."

| Path | Loaded into | Content this sprint |
| --- | --- | --- |
| `postgres/` | Postgres (`docker-entrypoint-initdb.d`) | Empty — schema/seed SQL lands with Module 6 (Sprint 5-6); identity session storage is stateless JWT this sprint (see `services/identity/README.md`), so Module 4 needed no Postgres schema |
| `keycloak/` | Keycloak realm import | `emg-realm.json` — local-dev-only realm `emg`. Sprint 2 (FEAT-02-1): confidential client `emg-identity-service` (Direct Access Grants), baseline roles, two human seed users. Sprint 3 (FEAT-02-3): three service-account-only confidential clients (`emg-svc-identity`, `emg-svc-authorization`, `emg-svc-audit`), their least-privilege roles, a client scope adding the shared `emg-internal-services` audience to service tokens, and one service-account user per client. **Local development credentials only — never used outside `docker-compose.yml`.** See `docs/engineering/service-identity-registration.md`. |
| `neo4j/` | Neo4j `import` directory | Empty — mock government entity fixtures (Person, Organization, Investigation, Risk, Policy, Decision) land with FEAT-05-1/05-2 (Sprint 7-8), per Engineering Master Plan §18 (Lab Prototype v1 Scope) |

This directory exists so the containerized orchestration (`docker-compose.yml`)
has a stable mount point from Sprint 1 onward; fixture data is authored only
in the owning module's sprint, per each sprint's "no business logic ahead of
schedule" constraint. `keycloak/emg-realm.json` is imported automatically by
`docker-compose.yml`'s `keycloak` service (`start-dev --import-realm`).
