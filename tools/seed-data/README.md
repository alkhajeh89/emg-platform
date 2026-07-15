# Seed / Mock Data Fixtures

Per Engineering Master Plan §13 (Development Environment Checklist): "Mock
government data fixtures available for Lab Prototype development."

| Path | Loaded into | Content this sprint |
| --- | --- | --- |
| `postgres/` | Postgres (`docker-entrypoint-initdb.d`) | Empty — schema/seed SQL lands with Module 4/6 (Sprint 2, Sprint 5-6) |
| `keycloak/` | Keycloak realm import | Empty — realm export lands with FEAT-02-1 (Sprint 2) |
| `neo4j/` | Neo4j `import` directory | Empty — mock government entity fixtures (Person, Organization, Investigation, Risk, Policy, Decision) land with FEAT-05-1/05-2 (Sprint 7-8), per Engineering Master Plan §18 (Lab Prototype v1 Scope) |

This directory exists so the containerized orchestration (`docker-compose.yml`)
has a stable mount point from Sprint 1 onward; no fixture data is authored
until the owning module's sprint, per Sprint 1's "no business logic"
constraint.
