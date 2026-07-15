# /services — Backend Modules (Modules 4-10)

One directory per backend module, per Engineering Master Plan §3 and §11
(Module Implementation Order): identity -> authz -> audit -> knowledge-graph
-> retrieval -> ai-orchestration -> decision-intelligence.

**Out of Sprint 1 scope.** Directories below are scaffolded (structure +
ownership metadata only, via `service.yaml`) so `/services` exists per
Module 1's approved repository structure, but no service contains business
logic, API endpoints, AI, or Knowledge Graph code yet — Sprint 1 covers
EPIC-01 (Foundation) only.

| Service | Governing Module | Target Epic | Target Sprint(s) |
| --- | --- | --- | --- |
| `identity/` | Module 4 — Identity & Authentication | EPIC-02 | 2-3 |
| `authz/` | Module 5 — Authorization & Policy | EPIC-03 | 4-5 |
| `audit/` | Module 6 — Audit, Provenance & Digital Evidence | EPIC-04 | 5-6 |
| `knowledge-graph/` | Module 7 — Knowledge Graph Platform | EPIC-05 | 7-9 |
| `retrieval/` | Module 8 — Search, GraphRAG & Retrieval | EPIC-06 / EPIC-07 | 10-14 |
| `ai-orchestration/` | Module 9 — AI Orchestration & Agents | EPIC-08 | 15-17 |
| `decision-intelligence/` | Module 10 — Decision Intelligence | EPIC-09 | 18-20 |

New services are scaffolded with `tools/scripts/new-service.sh <name>`, which
produces this same layout (`src/`, `tests/`, `README.md`, `service.yaml`).
