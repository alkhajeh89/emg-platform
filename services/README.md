# /services — Backend Modules (Modules 4-10)

One directory per backend module, per Engineering Master Plan §3 and §11
(Module Implementation Order): identity -> authz -> audit -> knowledge-graph
-> retrieval -> ai-orchestration -> decision-intelligence.

As of Sprint 2, `identity/` is implemented (FEAT-02-1 + FEAT-02-2); every
other directory remains scaffolded (structure + ownership metadata only, via
`service.yaml`) until its own sprint lands, per Module 1's approved
repository structure.

| Service | Governing Module | Target Epic | Target Sprint(s) | Status |
| --- | --- | --- | --- | --- |
| `identity/` | Module 4 — Identity & Authentication | EPIC-02 | 2-3 | In progress — FEAT-02-1/02-2 done (Sprint 2), FEAT-02-3/02-4 pending (Sprint 3) |
| `authz/` | Module 5 — Authorization & Policy | EPIC-03 | 4-5 | Scaffolded |
| `audit/` | Module 6 — Audit, Provenance & Digital Evidence | EPIC-04 | 6 | Active — FEAT-04-1 Audit Event Pipeline (Sprint 6); FEAT-04-2/04-3/04-4 later Audit sprints |
| `knowledge-graph/` | Module 7 — Knowledge Graph Platform | EPIC-05 | 7-9 | Scaffolded |
| `retrieval/` | Module 8 — Search, GraphRAG & Retrieval | EPIC-06 / EPIC-07 | 10-14 | Scaffolded |
| `ai-orchestration/` | Module 9 — AI Orchestration & Agents | EPIC-08 | 15-17 | Scaffolded |
| `decision-intelligence/` | Module 10 — Decision Intelligence | EPIC-09 | 18-20 | Scaffolded |

New services are scaffolded with `tools/scripts/new-service.sh <name>`, which
produces this same layout (`src/`, `tests/`, `README.md`, `service.yaml`).
