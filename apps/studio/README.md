# EMG Studio

EMG Studio is the browser application for governed EMG workspaces. Sprint 2 adds exact canonical entity-ID lookup, deep-linked entity exploration, approved provenance/history fields, and authorized relationship navigation to the enterprise shell.

## Application shell

Authenticated routes share `ApplicationShell`, which provides the desktop sidebar, mobile drawer, application bar, current-section indicator, global search entry, language controls, session status, and server-confirmed logout. Reusable visual primitives live in `src/components/ui.tsx`; feature workspaces remain separate components.

The shell queries only `GET /bff/auth/session`. An unauthenticated response renders the secure sign-in surface, and a session-service failure fails closed without rendering authenticated workspaces.

## Route map

| Route | Sprint 2 state |
| --- | --- |
| `/` | Redirects to `/dashboard` |
| `/dashboard` | Enterprise dashboard with honest data-source labels |
| `/entities` | Canonical entity-ID entry workspace |
| `/entities/{encoded-entity-id}` | Authorized entity detail, evidence, temporal history, and first relationship page |
| `/search?q={encoded-entity-id}` | Exact canonical entity-ID lookup with URL-reflected query state |
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

## Supported search semantics

Search is an exact, case-sensitive canonical entity-ID lookup backed by `GET /bff/api/knowledge-graph/v1/knowledge-graph/entities/{encoded-id}`. The global shell lookup uses the same contract. A successful result links to the deep-linked entity workspace; no backend object is persisted in browser storage.

The approved Knowledge Graph contract also supports structured entity listing filters and cursor pagination, but it does not define free-text, label, alias, relevance, or result-count semantics. Sprint 2 therefore does not present those features as search. Entity relationships use the approved neighbors read route; the workspace displays the first authorized page and reports honestly when more results exist.

## Sprint 2 limitations

- Dashboard operational metrics and recent activity are intentionally unavailable because no approved dashboard API exists.
- Free-text, fuzzy, label, alias, and relevance-ranked search are unavailable because no approved backend contract exists.
- Structured list filtering and cursor pagination exist in Knowledge Graph but are not presented as free-text search. Relationship continuation controls are not yet exposed.
- Evidence and temporal histories are displayed only when they are present in the approved entity response. No separate evidence or revision-list API is inferred.
- Knowledge Graph visualization, Evidence, Timeline, and Decisions remain planned route foundations. The Decision domain is accepted architecturally but has no implemented query service or API.
- The workspace remains read-only. No mutation, authoring, task, decision, or persistence capability is introduced.
