# Frontend Decision Register

| Decision ID | Decision Area | Status | Owner | Authority | Evidence | Blocking Questions |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| D-F-001 | Architecture Framework | TBD | TBD | TBD | None | Approval authority |
| D-F-002 | UI Architecture | TBD | TBD | TBD | None | Design System adoption |
| D-F-003 | Design System | TBD | TBD | TBD | None | Token strategy |
| D-F-004 | Client State | TBD | TBD | TBD | None | State management strategy |
| D-F-005 | Routing | TBD | TBD | TBD | None | Routing specification |
| D-F-006 | BFF Integration | **Accepted (2026-08-03)** | EMG Founder | Project Architect | **ADR-036** (`docs/architecture/EMG_ADR-036_APPLICATION_BFF_BOUNDARY.md`); ADR-014; ADR-034 | **Closed.** A BFF is mandatory; the browser never holds a service token; the BFF is not a PEP. One open sub-decision remains inside ADR-036 §5 — the downstream human-delegation mechanism (token exchange vs. signed propagated identity) — which must close before BFF implementation |
| D-F-007 | Authentication | **Accepted (2026-08-03)** | EMG Founder | Project Architect | **ADR-035** (`docs/architecture/EMG_ADR-035_HUMAN_PRINCIPAL_AUTHENTICATION.md`); ADR-025 §8.9 | **Closed.** OIDC Authorization Code + PKCE S256 through a confidential BFF client; ROPC rejected for browser use. Requires a Keycloak realm change before implementation |
| D-F-008 | Build | TBD | TBD | TBD | None | Tooling strategy |
| D-F-009 | Deployment | TBD | TBD | TBD | None | Deployment model |
| D-F-010 | Runtime | TBD | TBD | TBD | None | Runtime strategy |

These documents record unresolved frontend architecture decisions and do not constitute approved frontend architecture unless an individual decision is explicitly marked Accepted with supporting authority.

**Update — 2026-08-03.** D-F-006 and D-F-007 are the first entries in this
register to be Accepted, each carrying a named owner, a named decision
authority, and a governing accepted ADR. The remaining eight decisions
(D-F-001, D-F-002, D-F-003, D-F-004, D-F-005, D-F-008, D-F-009, D-F-010) are
**deliberately left open** and were not touched by that work. They block
high-fidelity design — in particular D-F-002 (UI Architecture) and D-F-003
(Design System / token strategy) — but do **not** block low-fidelity MVP
wireframes.
