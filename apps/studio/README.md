# EMG Studio

EMG Studio is the browser application for governed EMG workspaces. Sprint 1 establishes the reusable enterprise application shell, bilingual navigation, dashboard, and route foundation while preserving the existing read-only entity pilot.

## Application shell

Authenticated routes share `ApplicationShell`, which provides the desktop sidebar, mobile drawer, application bar, current-section indicator, global search entry, language controls, session status, and server-confirmed logout. Reusable visual primitives live in `src/components/ui.tsx`; feature workspaces remain separate components.

The shell queries only `GET /bff/auth/session`. An unauthenticated response renders the secure sign-in surface, and a session-service failure fails closed without rendering authenticated workspaces.

## Route map

| Route | Sprint 1 state |
| --- | --- |
| `/` | Redirects to `/dashboard` |
| `/dashboard` | Enterprise dashboard with honest data-source labels |
| `/entities` | Existing authorized `pilot-entity-001` retrieval |
| `/search` | Planned workspace; no search backend is fabricated |
| `/knowledge-graph` | Planned workspace |
| `/evidence` | Planned workspace |
| `/timeline` | Planned workspace |
| `/decisions` | Planned workspace |

## Localization

English and Arabic strings are centralized in `src/i18n/i18n.tsx`. The provider controls the document `lang` and `dir` attributes globally. English uses LTR and Arabic uses RTL. Canonical technical values—including entity IDs, classifications, revisions, service identifiers, and timestamps—are never translated and use LTR presentation where appropriate.

## Security boundary

The browser uses only same-origin `/bff/*` requests, rewritten by Next.js to Studio BFF. Studio never calls Knowledge Graph, Audit, Identity, Keycloak token endpoints, PostgreSQL, or Neo4j directly. It never receives or stores access, refresh, ID, service, or delegated tokens, and it never supplies tenant or clearance values.

Logout preserves the approved double-submit contract: Studio reads the non-HttpOnly CSRF cookie, submits it as `X-CSRF-Token` with the opaque session cookie, and returns to sign-in only after the BFF confirms logout and session revalidation returns 401.

## Local development

```bash
cp apps/studio/.env.example apps/studio/.env.local
npm ci
npm run dev --workspace @emg/studio
```

Open <http://localhost:3000>. Studio BFF and its dependencies must already be running.

## Sprint 1 limitations

- Dashboard operational metrics and recent activity are intentionally unavailable because no approved dashboard API exists.
- Search, Knowledge Graph visualization, Evidence, Timeline, and Decisions are route and navigation foundations only.
- The entity workspace remains read-only and supports the existing pilot entity contract.
- No mutation, authoring, task, decision, or search backend capability is introduced.
