# EMG Studio v1 user guide

## Sign in and session safety

Open the approved HTTPS Studio address and choose **Sign in**. Authentication is performed by the
configured identity provider. Studio never asks you to paste an access token and never stores
service or delegated tokens in browser storage. After authentication, the server confirms your
session, tenant, roles, and clearance. If that confirmation fails, Studio shows an unavailable or
signed-out state rather than displaying protected content.

Use **Sign out** when finished, especially on a shared device. If a session expires, sign in again;
do not repeatedly resubmit an operation. Contact support if authentication repeatedly loops or the
displayed identity is not yours.

## Available workspaces

- **Dashboard:** navigation and honest availability labels; it does not invent operational totals.
- **Search:** governed exact and prefix entity search.
- **Entities:** direct lookup by canonical entity ID and authorized entity detail.
- **Knowledge Graph:** deliberate, progressive exploration from an authorized root entity.

Evidence, Timeline, and Decisions are planned foundations and are not supported v1 workspaces.

## Governed search

Enter an entity ID, label, or alias on `/search`. Search supports deterministic exact and prefix
matching only. It does not provide fuzzy, semantic, substring, vector, facet, total-count, or
relevance-score behavior. Results include only entities the service authorizes for the current
tenant and clearance. A missing result does not prove that an entity exists or does not exist.

Use **Load more** only while it is offered. Pagination is bound to one authoritative revision. If a
continuation expires or becomes invalid, restart the search. The raw query and cursor remain in
memory and disappear on navigation or reload by design.

## Entity and graph exploration

Open a result to view its canonical entity detail. The response may include authorized evidence,
temporal fields, and relationships. The browser does not infer missing data.

In Knowledge Graph Explorer, select a root and explicitly expand visible neighbors. Each expansion
is independently authorized. The graph never claims completeness, hidden counts, or undisclosed
relationships. Use the relationship list for a keyboard-operable alternative to the SVG view.

## Language and accessibility

English and Arabic are supported. Arabic uses RTL layout; canonical identifiers, classifications,
timestamps, and API values remain unchanged and display LTR where needed. Do not translate or edit
canonical IDs before using them.

## User troubleshooting

| Symptom | Safe action |
| --- | --- |
| Sign-in loop or callback error | Stop retrying, record time and correlation/request ID if shown, and contact the Identity owner |
| Signed out while working | Sign in again; do not assume an interrupted mutation completed |
| “Unavailable” or readiness failure | Wait for operator confirmation; repeated refresh does not bypass fail-closed behavior |
| Search continuation rejected | Restart the search; do not edit the cursor |
| Expected result absent | Confirm tenant/clearance with support; absence reveals no hidden-result count |
| Graph expansion fails | Retry the single expansion once, then report root ID, visible node ID, time, and correlation ID—never the token or raw query |
| Arabic layout/copy defect | Report route, browser, viewport, locale, and screenshot with sensitive data removed |

Never send passwords, cookies, tokens, cursor values, raw confidential queries, or secret-bearing
URLs in support tickets.
