# EMG Studio

EMG Studio is the browser application for governed EMG workspaces. ADR-042 adds governed enterprise entity search alongside deep-linked entity exploration, approved provenance/history fields, and authorized relationship navigation.

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
| `/search` | Governed entity search with query and cursor held only in active in-memory UI state |
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

## Governed search

Studio submits `POST /bff/api/knowledge-graph/search` with the opaque session cookie, readable CSRF cookie echoed as `X-CSRF-Token`, and `credentials: "include"`. The browser calls no direct Knowledge Graph URL. Search supports only the backend's approved deterministic tiers: canonical ID exact, label exact, alias exact, canonical ID prefix, label prefix, and alias prefix. It exposes the localized safe match kind without relevance scores, aliases, snippets, totals, hidden counts, facets, or classification filtering controls.

Raw search text never enters the URL, navigation history, cookies, `localStorage`, `sessionStorage`, or IndexedDB. The global shell entry navigates to `/search` without transferring typed text. Search requests preserve the user's string unchanged; Studio performs no normalization or locale-specific matching.

Authorized continuation uses the opaque cursor exactly as returned. “Load more” appears only when `has_more` and `next_cursor` permit it, appends visible results, and defensively deduplicates by canonical entity ID. Cursors remain in memory for the active search only and are never decoded. An invalid continuation produces a safe restart state rather than silently changing revisions.

All search copy and match-kind labels are centralized for English and Arabic. Layout direction follows the selected locale, while entity IDs, entity types, classifications, revisions, and API enum values remain canonical and LTR where displayed. Every result links to `/entities/{encoded-entity-id}` without including the search query.

## Sprint 2 limitations

- Dashboard operational metrics and recent activity are intentionally unavailable because no approved dashboard API exists.
- Fuzzy, semantic/vector, substring, tokenized, metadata, facet, total-count, and relevance-ranked search remain unavailable.
- Search query and pagination state intentionally disappear on navigation or reload because confidentiality takes precedence over preserving browser state.
- Relationship continuation controls are not yet exposed in the entity workspace.
- Evidence and temporal histories are displayed only when they are present in the approved entity response. No separate evidence or revision-list API is inferred.
- Knowledge Graph visualization, Evidence, Timeline, and Decisions remain planned route foundations. The Decision domain is accepted architecturally but has no implemented query service or API.
- The workspace remains read-only. No mutation, authoring, task, decision, or persistence capability is introduced.
