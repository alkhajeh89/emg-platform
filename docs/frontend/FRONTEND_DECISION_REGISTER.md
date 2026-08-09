# Frontend Decision Register

| Decision ID | Decision Area | Status | Owner | Authority | Evidence | Blocking Questions |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| D-F-001 | Architecture Framework | **Accepted (2026-08-03)** | EMG Founder | Project Architect | **EMG_DESIGN_SYSTEM_BASELINE** (`docs/enterprise-design/EMG_DESIGN_SYSTEM_BASELINE.md`); ADR-036 | **Closed.** Next.js App Router + React + TypeScript with strict checking. Server-rendered application shell with bounded client interactivity. No browser service tokens; no direct datastore or internal repository access; BFF and authentication governed by ADR-036 and ADR-035. No implementation libraries beyond the minimum are selected, and no package files or scaffolding are created |
| D-F-002 | UI Architecture | **Accepted (2026-08-03)** | EMG Founder | Design System Governance Authority | **EMG_DESIGN_SYSTEM_BASELINE** (`docs/enterprise-design/EMG_DESIGN_SYSTEM_BASELINE.md`) §7, §8, §13 | **Closed.** Desktop-first; module-per-IA-group; three-tier component hierarchy (Primitive → Composite → Domain); mobile read-only |
| D-F-003 | Design System | **Accepted (2026-08-03)** | EMG Founder | Design System Governance Authority | **EMG_DESIGN_SYSTEM_BASELINE** (`docs/enterprise-design/EMG_DESIGN_SYSTEM_BASELINE.md`) §3, §6; `EMG_VISUAL_IDENTITY_DECISION.md` | **Closed.** Three-tier token architecture with semantic-only component consumption; Institutional Neutral identity direction; classification colour range is exclusive. Token roles fixed; final values remain a Figma implementation detail |
| D-F-004 | Client State | **Accepted (2026-08-03)** | EMG Founder | Project Architect | ADR-036 D-8; **EMG_DESIGN_SYSTEM_BASELINE** (`docs/enterprise-design/EMG_DESIGN_SYSTEM_BASELINE.md`) | **Closed.** Server state keyed `(tenant, entity, revision)` and clearance; immutable revisions cacheable; head reads and classified payloads never cached; no classified payload, token, or tenant identifier in browser storage |
| D-F-005 | Component governance (formerly "Routing") | **Accepted (2026-08-03)** | EMG Founder | Design System Governance Authority | **EMG_DESIGN_SYSTEM_BASELINE** (`docs/enterprise-design/EMG_DESIGN_SYSTEM_BASELINE.md`) §8 | **Closed.** Three-tier hierarchy with mandatory admission criteria: both themes, both directions, both densities, keyboard support, screen-reader semantics, and all state variants including **`denied`**. Routing follows the Next.js App Router convention adopted under D-F-001 |
| D-F-006 | BFF Integration | **Accepted (2026-08-03)** | EMG Founder | Project Architect | **ADR-036** (`docs/architecture/EMG_ADR-036_APPLICATION_BFF_BOUNDARY.md`); ADR-014; ADR-034; ADR-038 | **Closed and implemented in Phase 2B.** `apps/studio-bff` is mandatory; the browser never holds a Service Principal credential; the BFF is not a PEP. ADR-038 delegation uses RFC 8693 token exchange and the mandatory Keycloak capability verification passed. Production realm values, TLS, and deployment remain operational prerequisites. |
| D-F-007 | Authentication | **Accepted (2026-08-03)** | EMG Founder | Project Architect | **ADR-035** (`docs/architecture/EMG_ADR-035_HUMAN_PRINCIPAL_AUTHENTICATION.md`); ADR-025 §8.9 | **Closed.** OIDC Authorization Code + PKCE S256 through a confidential BFF client; ROPC rejected for browser use. Requires a Keycloak realm change before implementation |
| D-F-008 | Localization and RTL (formerly "Build") | **Accepted (2026-08-03)** | EMG Founder | Design System Governance Authority | ADR-018; **EMG_DESIGN_SYSTEM_BASELINE** (`docs/enterprise-design/EMG_DESIGN_SYSTEM_BASELINE.md`) §4, §5, §11 | **Closed.** Full RTL mirroring via logical properties; direction is a mode, never a duplicated component; evidence never translated; security messages authored in both languages. **Calendar: Gregorian is authoritative and default.** Arabic UI may show an optional secondary Hijri date; evidence, audit, revisions, APIs, identifiers, and exports retain Gregorian ISO-8601. Hijri conversion is presentational only and never changes stored meaning |
| D-F-009 | Accessibility (formerly "Deployment") | **Accepted (2026-08-03)** | EMG Founder | Design System Governance Authority | **EMG_DESIGN_SYSTEM_BASELINE** (`docs/enterprise-design/EMG_DESIGN_SYSTEM_BASELINE.md`) §10 | **Closed.** WCAG 2.2 Level AA. Graph and timeline each require a keyboard-navigable equivalent exposing the same data. No state conveyed by colour alone. Deployment topology remains a production-readiness dependency, not a frontend governance decision |
| D-F-010 | Motion and real-time (formerly "Runtime") | **Accepted (2026-08-03)** | EMG Founder | Design System Governance Authority | **EMG_DESIGN_SYSTEM_BASELINE** (`docs/enterprise-design/EMG_DESIGN_SYSTEM_BASELINE.md`) §12 | **Closed.** Purposeful motion only; `prefers-reduced-motion` honoured absolutely. **MVP is request/response only** — no websockets, no polling, no live push; no event-push backend exists. Refresh is explicit with a visible "as of" timestamp |

These documents record unresolved frontend architecture decisions and do not constitute approved frontend architecture unless an individual decision is explicitly marked Accepted with supporting authority.

**Update — 2026-08-03 (a).** D-F-006 and D-F-007 were the first entries in this
register to be Accepted, governed by ADR-036 and ADR-035 respectively.

**Update — 2026-08-03 (b) — register complete.** All ten decisions are now
Accepted. D-F-001 through D-F-005 and D-F-008 through D-F-010 are governed by
`docs/enterprise-design/EMG_DESIGN_SYSTEM_BASELINE.md`, which is the **canonical
design-system authority**; `docs/frontend/design-system/` is **derived
implementation guidance** and is subordinate to it.

Three entries were renamed to match the decision actually taken: D-F-005
(Routing → Component governance), D-F-008 (Build → Localization and RTL), and
D-F-009 (Deployment → Accessibility). Build tooling and deployment topology are
not frontend governance decisions; deployment remains a production-readiness
dependency.

Pre-ADR-035/036 authentication and BFF guidance under `docs/frontend/` — in
particular `FRONTEND_BFF_GUIDE.md`, `FRONTEND_AUTHENTICATION.md`,
`AUTHENTICATION_FLOW.md`, and `BFF_INTEGRATION.md` — is **superseded** by
ADR-035 and ADR-036 and must not be treated as authority.
`FRONTEND_WEBSOCKET_ARCHITECTURE.md` is superseded for MVP by D-F-010.
