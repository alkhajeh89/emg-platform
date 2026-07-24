
# EMG™ AI Context v2.0
## Enterprise AI Engineering Context

**Status:** Authoritative AI Context
**Audience:** Gemini, ChatGPT, Claude, Copilot, Cursor, Windsurf

---

# 1. Purpose

This document defines how AI assistants must understand, navigate, and contribute to the EMG repository.

It is **not** an architecture document. It is the entry point that explains:
- what EMG is,
- which documents are authoritative,
- how documentation is organized,
- how implementation decisions are made,
- which documents must be loaded for each task.

---

# 2. Project Overview

**Enterprise Memory Graph (EMG™)** is an Enterprise Intelligence Platform for governments, defense, aviation, critical infrastructure, and large enterprises.

Core capabilities include:

- Enterprise Memory
- Knowledge Graph
- Decision Intelligence
- Enterprise Search
- AI Copilot
- Digital Twins
- Explainable AI
- Governance
- Provenance
- Investigation

Mission:

> Every organization deserves a memory.

---

# 3. Repository Structure

```
docs/
architecture/
engineering/
enterprise-design/
product/
phases/
sprints/
ai-context/

services/
libs/
infra/
apps/
observability/
tools/
```

---

# 4. Documentation Hierarchy

Priority (highest → lowest)

1. Product Vision
2. Architecture Baseline
3. ADRs
4. Engineering Standards
5. Enterprise Design
6. Sprint Design
7. Implementation

Implementation must never override architecture.

---

# 5. Source of Truth Matrix

| Domain | Authoritative Source |
|---------|----------------------|
| Product | docs/product |
| Architecture | docs/architecture |
| Backend | docs/engineering |
| Frontend | docs/enterprise-design |
| Sprint | Current sprint design |
| Code Quality | definition-of-done.md |

---

# 6. AI Operating Principles

- Preserve architecture.
- Never invent undocumented architecture.
- Follow DDD boundaries.
- Respect Hexagonal Architecture.
- Prefer composition over coupling.
- Keep services autonomous.
- Generate production-ready code only.

---

# 7. Coding Quality

Required:

- mypy --strict
- ruff clean
- black formatted
- pytest passing
- No TODO
- No FIXME
- No placeholders

---

# 8. Security Principles

- Zero Trust
- Least Privilege
- Immutable Audit
- Explainable AI
- Human-in-the-loop

---

# 9. Frontend Standards

Technology stack:

- React
- TypeScript
- Next.js
- Tailwind CSS
- shadcn/ui

Reference:

- UX_OVERVIEW.md
- DESIGN_SYSTEM.md
- SCREEN_SPECIFICATIONS.md
- FRONTEND_ARCHITECTURE.md

---

# 10. Backend Standards

- Domain Driven Design
- Ports & Adapters
- Event Driven
- API Contracts
- Independent services
- Shared libraries only for cross-cutting concerns

---

# 11. Repository Navigation

## Product Questions
Read:
- Product Vision
- Product Architecture Freeze

## Architecture Questions
Read:
- Architecture Baseline
- Relevant ADRs

## Backend Tasks
Read:
- Engineering docs
- Current Sprint

## Frontend Tasks
Read:
- Enterprise Design docs
- Current Sprint

---

# 12. AI Loading Strategy

Always load:

1. README_FOR_AI.md
2. CURRENT_PHASE.md
3. DOCUMENT_INDEX.md
4. TASK_ROUTING.md

Then load only task-specific documentation.

---

# 13. Review Checklist

Before completing work verify:

- Architecture preserved
- Tests pass
- Documentation updated
- Security maintained
- No technical debt introduced

---

# 14. AI Prompt Contract

The assistant shall:

- Ask when architecture is missing.
- Never guess architectural intent.
- Never contradict ADRs.
- Produce deterministic, production-ready output.

---

# 15. Current Phase Template

Maintain CURRENT_PHASE.md with:
- Active phase
- Active sprint
- Current priorities
- Exit criteria

---

# 16. Document Index Template

Maintain DOCUMENT_INDEX.md describing:
- Purpose
- Audience
- Authority
- Dependencies

---

# 17. Task Routing Template

Maintain TASK_ROUTING.md mapping:
- Backend
- Frontend
- Architecture
- Infrastructure
- Security
- Testing
to required documentation.

---

# 18. Governance

Every architectural change requires:

1. Design
2. Review
3. ADR (if applicable)
4. Approval
5. Implementation
6. Testing
7. Documentation update

---

# 19. Success Criteria

An AI contribution is successful only if it:

- Preserves architecture
- Meets engineering standards
- Passes quality gates
- Keeps documentation synchronized
- Respects repository conventions

---

End of Document
