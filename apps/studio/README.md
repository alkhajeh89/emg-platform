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
| `/knowledge-graph` | Explorer root discovery through governed in-memory search |
| `/knowledge-graph/{encoded-entity-id}` | Progressive authorized graph exploration rooted at a canonical entity |
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

## Production runtime

Studio is released as the governed `studio` image from `apps/studio/Dockerfile`. The multi-stage
build uses the root npm lock, emits Next.js standalone output, and copies only the standalone server
and static assets into the non-root production image. It contains no credential or direct Knowledge
Graph address. `STUDIO_BFF_INTERNAL_URL` is the non-secret, build-time server destination used by
the `/bff/*` rewrite; the governed production build uses `http://emg-studio-bff:8000`. It is never
emitted as public browser configuration.

Production traffic follows `browser -> ingress -> Studio -> Studio BFF`. The BFF OIDC callback is
`/bff/auth/callback`, so it traverses the same Studio proxy. `/healthz` is process liveness and
`/readyz` confirms the Studio server can serve requests; dependency readiness remains owned by the
BFF `/readyz` probe. The hardened Deployment runs as UID/GID 10001 with a read-only root, dropped
capabilities, no service-account token, bounded resources, and allow-listed Studio-to-BFF traffic.

Canonical validation uses `npm ci --workspace @emg/studio --include-workspace-root`, followed by
the Studio test, typecheck, lint, build and `npm audit --omit=dev --audit-level=high` gates.
Tag releases include Studio in the common Trivy, CycloneDX, GHCR, Cosign, provenance and immutable
digest workflow. Rollback selects a prior complete release set; images are never mixed or retagged.

## Governed search

Studio submits `POST /bff/api/knowledge-graph/search` with the opaque session cookie, readable CSRF cookie echoed as `X-CSRF-Token`, and `credentials: "include"`. The browser calls no direct Knowledge Graph URL. Search supports only the backend's approved deterministic tiers: canonical ID exact, label exact, alias exact, canonical ID prefix, label prefix, and alias prefix. It exposes the localized safe match kind without relevance scores, aliases, snippets, totals, hidden counts, facets, or classification filtering controls.

Raw search text never enters the URL, navigation history, cookies, `localStorage`, `sessionStorage`, or IndexedDB. The global shell entry navigates to `/search` without transferring typed text. Search requests preserve the user's string unchanged; Studio performs no normalization or locale-specific matching.

Authorized continuation uses the opaque cursor exactly as returned. “Load more” appears only when `has_more` and `next_cursor` permit it, appends visible results, and defensively deduplicates by canonical entity ID. Cursors remain in memory for the active search only and are never decoded. An invalid continuation produces a safe restart state rather than silently changing revisions.

All search copy and match-kind labels are centralized for English and Arabic. Layout direction follows the selected locale, while entity IDs, entity types, classifications, revisions, and API enum values remain canonical and LTR where displayed. Every result links to `/entities/{encoded-entity-id}` without including the search query.

## Knowledge Graph Explorer

The Explorer uses only the existing entity and neighbors APIs through same-origin `/bff/*` requests. Users may choose a root through governed search, open a search result in the graph, enter from an existing entity detail, or use a canonical entity deep link. Search text remains in memory and never enters the graph URL; only the already-authorized canonical root ID is routed.

Loading a root retrieves that entity and one authorized neighbor page. Further expansion occurs only after an explicit user action on a visible entity. Nodes are deduplicated by canonical entity ID and relationships by the returned `via_edge_id`. Each entity keeps its own opaque continuation cursor and failure state. Cursors are forwarded unchanged and never decoded. All expansion requests remain pinned to the root revision.

The deterministic native-SVG view and keyboard-accessible relationship list are two representations of the same in-memory authorized graph state. Both support entity selection, explicit expansion, local continuation, relationship selection, and encoded entity-detail links. On smaller screens the layout stacks the detail panel and emphasizes the representation switcher. No graph visualization dependency or browser persistence was added.

The Explorer never claims completeness and does not display total nodes, total relationships, hidden/denied counts, or inferred classified existence. The frontend applies only an internal visible-node rendering safeguard; it is not presented as backend cardinality. Neighbor responses distinguish `directed` and `undirected` relationships but do not expose endpoint orientation, so the SVG deliberately does not invent arrow direction.

## Sprint 2 limitations

- Dashboard operational metrics and recent activity are intentionally unavailable because no approved dashboard API exists.
- Fuzzy, semantic/vector, substring, tokenized, metadata, facet, total-count, and relevance-ranked search remain unavailable.
- Search query and pagination state intentionally disappear on navigation or reload because confidentiality takes precedence over preserving browser state.
- Relationship continuation controls are not yet exposed in the entity workspace.
- Evidence and temporal histories are displayed only when they are present in the approved entity response. No separate evidence or revision-list API is inferred.
- Evidence, Timeline, and Decisions remain planned route foundations. The Decision domain is accepted architecturally but has no implemented query service or API.
- Explorer expansion is deliberate and bounded: there is no automatic multi-hop traversal, physics layout, completeness estimate, or cross-session graph persistence.
- The workspace remains read-only. No mutation, authoring, task, decision, or persistence capability is introduced.
