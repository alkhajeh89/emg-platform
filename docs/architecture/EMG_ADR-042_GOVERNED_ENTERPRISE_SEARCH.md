# EMG ADR-042 — Governed Enterprise Search

**Status:** Accepted
**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Project Architect
**Decision Date:** 2026-08-10
**Baseline:** `develop` at `12774805b00a7b9e1d3cd4dbc709505ac3f1995a`.
**Resolves on acceptance:** ADR-024 §20.8 and §24's free-text-search deferral only.
**Related:** ADR-015 (Unified Enterprise Observability), ADR-018 (Bilingual Enterprise
Architecture), ADR-023 (Knowledge Graph Revision History & Navigation), ADR-024
(Knowledge Graph Query Engine), ADR-025 (Knowledge Graph Tenant & Authorization Model),
ADR-026 Revision 2 (Knowledge Graph Classification Enforcement Model), ADR-028 (Audit
Reconciliation), ADR-030 Revision 4 (Mutation Ledger & Atomic Idempotency), ADR-034
(Security State and Service Trust), ADR-035 (Human Principal Authentication), ADR-036
(Application and BFF Boundary), ADR-038 (Human Identity Delegation Architecture), and
ADR-041 (Production Provisioning Ownership & Bootstrap Contract).
**Supersedes:** Only ADR-024's explicit deferral of free-text search without settled
semantics and index design. Every other ADR-024 decision remains unchanged.

> **This ADR authorizes architecture only after acceptance.** It does not implement a
> search endpoint, persistence representation, migration, index, cursor codec, Audit
> behavior, Studio integration, or BFF change. Implementation requires separate review.

---

## 1. Context

ADR-024 deliberately provides canonical entity lookup and exact structured filters, not
human-oriented search. ADR-024 §20.8 rejects free-text search until a dedicated ADR defines
matching semantics and an index strategy. Studio therefore supports only exact canonical
entity-ID lookup today.

The canonical graph already contains three useful identity fields: `node_id`, `label`, and
`aliases`. PostgreSQL is authoritative for immutable graph revisions. Neo4j is a rebuildable,
best-effort current-head serving projection accepted only when its revision and content hash
match the authoritative PostgreSQL head. Knowledge Graph derives tenant from verified caller
identity, enforces permission through its Policy Enforcement Point, prunes classified objects
through the existing PolicyEngine, and synchronously audits delegated human reads with
fail-closed behavior.

Searching an in-memory `MemoryGraph` would require an O(N) tenant-graph scan for every
request. A result limit does not bound that candidate scan. Conversely, choosing Neo4j or a
new external engine as search authority would introduce unresolved staleness, authorization,
recovery, and operational contracts. A governed search capability therefore needs a
PostgreSQL-authoritative, indexed, deterministic design that preserves the existing security
path.

## 2. Scope and non-supersession

This ADR governs initial current-head entity search only. It defines search authority,
searchable fields, normalization, matching, ordering, authorization-safe pagination,
revision consistency, cursor integrity, query bounds, persistence/index strategy, delegated
Audit behavior, API shape, BFF compatibility, observability, failure behavior, and minimum
Studio constraints.

It does not alter graph identity, revision construction, authorization roles, PolicyEngine
semantics, classification ordering, tenant derivation, delegated identity, Audit custody,
Neo4j's projection role, browser sessions, or the generic Studio BFF trust boundary.

## 3. Decision summary

EMG SHALL provide deterministic entity search over a transactionally maintained,
PostgreSQL-derived representation of each searchable authoritative graph revision. Initial search SHALL
cover canonical entity ID, canonical label, and aliases using versioned Unicode
normalization, exact and prefix matching only. Results SHALL be ordered by fixed match tier
and canonical entity ID, authorized and classification-pruned before exposure and page
construction, bound to one authoritative revision, and continued with an opaque encrypted
and authenticated cursor. No totals, facets, snippets, raw matched aliases, or numeric
relevance scores SHALL be returned.

## 4. D-1 — Search authority and consistency

1. PostgreSQL remains the sole authoritative persistence boundary.
2. Initial search SHALL use an indexed search representation stored in the Knowledge Graph
   PostgreSQL boundary and derived only from validated canonical `MemoryNode` values.
3. Search rows for a new current-head revision R SHALL be created in the same database
   transaction that makes revision R authoritative. A committed head without its complete
   search representation is invalid and SHALL fail closed for search. Retirement of an older
   representation is a separate governed retention operation constrained by D-8.
4. Every search representation SHALL carry `tenant_id`, `revision_number`, canonical
   `node_id`, classification, normalized label, and the normalizer version. Alias terms SHALL
   be revision- and entity-bound.
5. Search SHALL query the representation for an explicitly pinned authoritative revision;
   it SHALL never infer authority from the newest search row alone.
6. Neo4j SHALL NOT be queried for initial search and SHALL NOT become a search,
   authorization, classification, revision, or pagination authority.
7. Elasticsearch, OpenSearch, vector databases, and other external search infrastructure
   are prohibited for the initial implementation.

The representation is derived and rebuildable, but transactionally complete at commit. The
authoritative graph revision remains the source from which it can be verified or rebuilt.

## 5. D-2 — Initial searchable fields

The closed initial field allow-list is:

1. canonical `node_id`;
2. canonical `label`;
3. each canonical alias in `aliases`.

Owner, source, evidence, histories, classifications, relationship fields, arbitrary
metadata, and evidence text SHALL NOT be searched. A match SHALL return the canonical entity
summary, not the matched alias or a text snippet.

Adding a field is an information-disclosure expansion. It requires an accepted amendment or
new ADR that identifies field provenance, classification inheritance, normalization,
indexing, response behavior, and leakage tests. A migration or UI change alone cannot expand
the allow-list.

## 6. D-3 — Versioned normalization

One shared, explicitly versioned search normalizer SHALL produce stored comparison keys and
normalize incoming `q`. Backend semantics SHALL be independent of UI language, host locale,
runtime locale, and database locale.
Normalizer version 1 SHALL perform, in order:

1. reject invalid Unicode and prohibited control characters;
2. Unicode NFKC normalization;
3. Unicode default case folding;
4. map every contiguous Unicode whitespace sequence to one ASCII space; and
5. trim leading and trailing whitespace.

The normalized result SHALL be non-empty. One canonical conformance-vector suite SHALL run
unchanged against authoritative write-time indexing, populated-database migration/backfill,
rebuild tooling, and request-time query normalization. It SHALL NOT delegate semantic
normalization to a host locale, locale-dependent PostgreSQL collation, implicit database
case conversion, or Studio. A normalization-semantic or Unicode-data-version change requires
a governed normalizer-version transition, explicit mixed-version compatibility rule, and
tested reindex/backfill strategy; it SHALL NOT reinterpret stored keys silently.

Canonical values returned to callers remain unchanged. Normalization creates search keys;
it does not change entity identity, labels, or aliases.

## 7. D-4 — Matching and duplicate elimination

Initial matching SHALL support only whole-key exact and beginning-of-key prefix matching
against normalized keys. It SHALL NOT perform token matching, word reordering, internal
substring matching, stemming, transliteration, accent removal beyond NFKC, edit-distance
matching, fuzzy matching, phonetic matching, semantic matching, or vector similarity.

Aliases use the same normalizer and exact/prefix rules as labels. When one entity matches
multiple fields or aliases, it SHALL appear once at its best (lowest-numbered) tier. Search
SHALL NOT return which alias matched.

## 8. D-5 — Deterministic ordering and explainability

Results SHALL use these tiers:

| Tier | Match |
| :--- | :--- |
| 1 | Canonical entity ID exact |
| 2 | Canonical label exact |
| 3 | Any alias exact |
| 4 | Canonical entity ID prefix |
| 5 | Canonical label prefix |
| 6 | Any alias prefix |

Within a tier, results SHALL order by canonical `node_id` using the canonical deterministic
ordering already used by `MemoryGraph`, not a locale-sensitive collation. The ordering tuple
is `(tier, node_id)`. One safe enum-like `match_kind` MAY expose the tier for an already
authorized result; no numeric relevance score SHALL be exposed.

## 9. D-6 — Authorization before observability

Search SHALL use this algorithm:

1. authenticate and independently validate the caller using existing Knowledge Graph rules;
2. derive tenant exclusively from the verified caller;
3. authorize `read` on `knowledge-graph.entity` using the existing delegated-aware PEP;
4. resolve and pin an authoritative graph revision;
5. retrieve only candidates for that tenant and revision in deterministic tier/ID order;
6. evaluate every candidate through the existing PolicyEngine classification contract;
7. discard denied candidates before constructing response items, continuation metadata, or
   `has_more`;
8. continue bounded candidate retrieval until the authorized page is full or the candidate
   set is exhausted; and
9. determine `has_more` only by finding at least one further authorized candidate.

No browser or BFF decision is authoritative. Authentication, tenant resolution, permission
authorization, and PolicyEngine classification authorization SHALL be re-evaluated from
current trusted state on every request, including every continuation. Revoked access takes
effect immediately. A cursor never freezes or restores authorization and SHALL contain no
clearance, role, permission, policy outcome, or authorization state. Current authorization
may reduce or eliminate results relative to an earlier page, but cannot expand access based
on an earlier decision.

The cursor's last-returned `(tier, node_id)` is an ordering boundary only. If that entity is
no longer authorized, the service MAY still use the confidential boundary internally to
resume deterministic scanning, but SHALL neither re-authorize nor expose it. If current
authentication, tenant binding, or entity-read permission fails, continuation fails under
the normal uniform authentication/authorization contract. Classification changes SHALL be
handled through current candidate pruning and authorized `has_more` computation, without
revealing that the boundary or skipped candidates became unauthorized.

The response SHALL expose no total count, hidden count, scanned count, denied count, facet,
classification distribution, raw alias, snippet, or cursor state derived from a denied
entity. Page length may be less than the requested limit only when no further authorized
candidate exists. If the bounded candidate-work ceiling is reached before that fact can be
established, the whole request SHALL fail with a generic retryable bounded-work error; it
SHALL NOT return a partial page or a cursor derived from a denied candidate.

## 10. D-7 — Classification

Search SHALL reuse ADR-026 Revision 2 and the existing PolicyEngine/classification gate
without implementing classification comparison, clearance ordering, or alternate pruning in
SQL, the search service, BFF, or Studio.

Classification may be carried in the internal search representation to load the resource
attributes required by the existing gate. It is never itself a preauthorization substitute.
Denied entities SHALL be indistinguishable from absent entities in search output. A
classification evaluation error SHALL fail the search request closed.

## 11. D-8 — Revision consistency

The first page SHALL pin the authoritative PostgreSQL graph head revision. The response SHALL
include the existing safe `revision_context`. A continuation cursor SHALL bind to that exact
tenant, normalized-query digest, normalizer version, revision number, and ordering position.

Later graph commits SHALL NOT change a continuation's result set. Continuation SHALL query
the pinned revision and SHALL re-evaluate current authorization/classification. If the pinned
revision or its complete search representation is unavailable, corrupt, outside retention,
or unverifiable, the request SHALL fail explicitly; it SHALL NOT silently move to current
head or mix revisions.

Cursor validity is strictly subordinate to retention of the pinned authoritative revision
and its complete search representation. A cursor expiry SHALL never extend beyond the
server's guaranteed availability window for both. Every still-valid cursor SHALL have its
pinned revision and search representation retained. If either is unavailable, corrupt,
unverifiable, or retired, continuation fails safely and explicitly; the server SHALL never
silently use current head, rebuild against a different revision, or reinterpret the cursor.
Key rotation SHALL NOT change this rule or create cross-revision continuation.

The initial implementation SHALL retain complete search state for the current head plus only
the bounded set of prior revisions required to honor unexpired cursors. It SHALL NOT retain a
search copy for every historical graph revision by default. Cursor issuance SHALL select an
expiry no later than the configured guaranteed retirement point for the pinned representation,
and retirement SHALL verify that no unexpired cursor window remains. The concrete bounded
window requires storage/cardinality analysis and operational configuration aligned with
ADR-023 retention; this ADR invents no duration. Historical graph revisions remain governed
by ADR-023 and are not made searchable merely because continuation state is retained.

## 12. D-9 — Cursor model

The Knowledge Graph service SHALL issue an opaque, versioned cursor protected with
AES-256-GCM using an environment-supplied, rotatable cursor key and a fresh unique nonce per
cursor. Encryption is required, rather than a plaintext MAC alone, because continuation
state contains tenant binding, a query digest susceptible to offline guessing, and a
canonical entity ordering boundary that may cease to be authorized after issuance. Those
values require confidentiality as well as integrity and authenticity. Cursor keys SHALL
remain service-side and SHALL follow
ADR-034/ADR-041 secret custody; they SHALL never enter source control, logs, BFF state, or the
browser outside the opaque cursor string.

The public envelope SHALL contain only format version, non-secret key identifier, nonce, and
ciphertext/tag; every envelope field SHALL be authenticated. The plaintext SHALL contain only:

- cursor format version;
- normalizer version;
- tenant binding;
- pinned revision number;
- digest of the normalized query, never raw query text;
- last returned authorized `(tier, node_id)` position;
- issuance/expiry metadata.

It SHALL NOT contain raw query text, clearance, roles, tokens, result totals, database
offsets, tenant secrets, or denied entity identifiers. The authenticated context SHALL bind
the cursor to the endpoint, normalized-query digest, tenant, pinned revision, and deployed
contract version. Cursor decoding SHALL enforce a bounded encoded size before cryptographic
work. No repository or default production key is permitted. Issuance SHALL use the active key
identifier; bounded rotation MAY accept explicitly configured prior keys only until both
their cursor acceptance window and pinned-revision retention window end. Unknown, disabled,
retired, or out-of-window key identifiers SHALL fail closed and SHALL never trigger fallback,
re-signing, or revision substitution. No secrets vendor is selected by this ADR.

Malformed, tampered, expired, wrong-tenant, wrong-query, wrong-version, unavailable-revision,
or unsupported-key cursors SHALL fail closed with one uniform invalid-continuation response.
They SHALL never fall back to a first page.

## 13. D-10 — Query and work bounds

Initial limits are architectural safety ceilings, not service-level objectives:

- `q`: 1–128 Unicode scalar values after normalization and no more than 512 UTF-8 bytes;
- default page size: 20;
- maximum page size: 100, below ADR-024's general query ceiling of 200;
- only one `q`, one `limit`, and zero or one `cursor` value are accepted;
- empty or whitespace-only `q` is invalid and SHALL NOT enumerate entities;
- invalid UTF-8, unpaired surrogate input, NUL, and C0/C1 control characters other than
  whitespace accepted by the normalizer are rejected; valid Arabic and other Unicode format
  behavior is not narrowed by an ASCII allow-list;
- wildcard syntax has no special meaning; `%`, `_`, and equivalent database metacharacters
  SHALL be safely escaped and treated literally; and
- candidate retrieval SHALL use bounded batches and a configured per-request candidate-work
  ceiling.

The work ceiling and batch size are implementation configuration bounded by repository-tested
hard maxima. Exceeding the work ceiling SHALL fail the whole request generically and SHALL
not expose filtered counts or change security semantics. Rate limiting and operational quotas may be added at established platform
boundaries but cannot replace indexed execution or service-side bounds.

## 14. D-11 — PostgreSQL representation and indexes

The initial implementation SHALL add a Knowledge Graph-owned migration for a normalized
entity-search document and normalized search terms. The logical model SHALL provide:

- one revision-bound entity document keyed by `(tenant_id, revision_number, node_id)` with
  canonical safe response fields, classification, normalizer version, and content/hash
  verification metadata; and
- zero or more revision-bound terms keyed by tenant, revision, entity, field kind, and
  normalized term, with duplicate aliases eliminated.

Rows SHALL be generated from validated canonical nodes inside authoritative revision commit,
not from browser input or Neo4j. Foreign keys or equivalent transactionally enforced
integrity SHALL prevent terms from outliving their entity document/revision. Rebuilds SHALL
derive from authoritative revisions and verify content hashes before publication.

Initial indexes SHALL be B-tree indexes whose leading keys are `tenant_id` and
`revision_number`, followed by field kind/normalized term and canonical node ID as needed for
exact/prefix lookup and deterministic continuation. The implementation SHALL select the
simplest deterministic prefix mechanism proven by conformance and `EXPLAIN` evidence; this
ADR does not prematurely mandate a PostgreSQL operator class, collation, generated
expression, or extension. User text SHALL never be interpolated into a pattern or SQL
fragment, and index semantics SHALL not alter the versioned application normalizer.

`pg_trgm`, PostgreSQL full-text search, generated locale-dependent expressions, and external
extensions are not required or approved for exact/beginning-prefix semantics. An extension
requires a later decision with deployment, backup, migration, and query-plan evidence.

Migration tests SHALL cover clean creation, rollback policy, populated-revision backfill,
idempotent/restart-safe backfill, tenant isolation, hash/revision verification, and failure
without partial publication. Representative `EXPLAIN` plans SHALL prove approved index usage
for exact, prefix, and continuation queries; sequential scans of the search term corpus are a
release blocker.

## 15. D-12 — Governed Audit

Search is a governed delegated read. Existing ADR-038 synchronous, fail-closed attribution
SHALL apply to delegated search success, denial, validation failure after caller attribution,
and execution failure. The action SHALL be `search` on the existing
`knowledge-graph.entity` resource type unless a later policy ADR introduces a distinct
resource; authorization itself remains the existing entity `read` permission.

Audit SHALL record only the existing trusted tenant, Human Principal, Acting Service,
correlation ID, action, outcome, requested page size, whether continuation was used,
normalizer version, and a bounded query-length bucket/category. It SHALL NOT record raw or
normalized query text, query digests usable for correlation across tenants, result contents,
matched aliases, snippets, counts, cursors, tokens, clearance, or policy inputs.

Non-delegated service reads retain their existing audit contract; this ADR does not silently
expand Audit scope beyond delegated governed operations. Audit submission failure SHALL fail
closed exactly as ADR-038 requires.

## 16. D-13 — API contract

Knowledge Graph SHALL expose a read-only search operation using POST with a JSON body:

```text
POST /v1/knowledge-graph/search
Content-Type: application/json

{
  "q": "<query>",
  "limit": <1..100, optional>,
  "cursor": "<opaque continuation, optional>"
}
```

POST is selected for query confidentiality, not mutation semantics. The operation remains
safe, read-only, and side-effect-free with respect to graph/search state; mandatory delegated
Audit attribution is the existing governed-read side effect. GET with infrastructure-wide
query-string redaction is rejected because EMG cannot prove redaction across browser history,
copied URLs, access/reverse-proxy logs, tracing, monitoring, and referrer behavior. A custom
header is rejected because it would misuse header infrastructure and still require pervasive
redaction. The request body SHALL be treated as sensitive and excluded from default access
logs, reverse-proxy logs, traces, telemetry, error capture, and correlation metadata.

`q` is required on every request, including continuation, and is verified against the
cursor-bound query digest. `limit` defaults to 20 and MAY be reduced on continuation but
SHALL NOT be increased beyond the cursor-bound/original safety context. `cursor` is optional.
No type, classification, metadata, tenant, clearance, language, ranking, or revision selector
is approved initially.

The response SHALL follow existing Knowledge Graph transport conventions:

```text
{
  "items": [
    {
      "entity": <EntitySummaryResponse>,
      "match_kind": "ID_EXACT | LABEL_EXACT | ALIAS_EXACT |
                     ID_PREFIX | LABEL_PREFIX | ALIAS_PREFIX"
    }
  ],
  "page_info": {
    "limit": <requested effective limit>,
    "returned_count": <authorized items in this response>,
    "next_cursor": <opaque string or null>,
    "has_more": <authorized continuation exists>
  },
  "revision_context": <QueryRevisionContextResponse>
}
```

`returned_count` is only the visible array length; it is not a total. The endpoint SHALL NOT
return total count, relevance score, matched text, matched alias, snippet, facet, owner,
evidence count, relationship count, or activity.

Error semantics SHALL use existing EMG error envelopes:

- 400: malformed/empty/over-limit query or duplicate parameters;
- 401: authentication/session/delegated credential failure as applicable;
- 403: permission denial, with existing delegated denial attribution;
- 400 with one stable public error code: any invalid continuation condition;
- 503/appropriate existing upstream-unavailable mapping: authoritative persistence or Audit
  dependency failure; and
- no special not-found response: a successful search with no authorized matches returns
  `items=[]`, `has_more=false`, and no total.

Public error detail SHALL NOT reveal tenant, revision retention, cursor plaintext, denied
entities, classification, or whether a query would match inaccessible data.

## 17. D-14 — Studio BFF and browser boundary

The existing generic GET-only Studio BFF Knowledge Graph proxy is insufficient for the
confidential POST contract. Implementation SHALL add one narrowly governed, read-only search
forwarding path. It SHALL accept only the exact versioned JSON schema in D-13, enforce body
and response-size bounds, preserve the existing opaque session and CSRF protections, perform
a fresh delegated credential exchange, forward only to the fixed Knowledge Graph search
route, strip unsafe upstream headers, and return the Knowledge Graph response without
re-ranking, enrichment, authorization, or tenant derivation.

The forwarding path SHALL reject browser-supplied tenant, clearance, principal, Acting
Service, authorization headers, and unknown body fields. It SHALL NOT become a general POST
proxy and SHALL NOT make the read-only search operation a mutation. Raw query text and the
request body SHALL be excluded from BFF/access/proxy logs, traces, telemetry, errors, and
correlation metadata. No service or delegated credential may reach the browser.

The browser path remains:

```text
Browser -> same-origin /bff/* -> Studio BFF -> Knowledge Graph
```

Knowledge Graph remains the PEP. Browser query, cursor, language, URL state, and navigation
state are untrusted inputs, never identity or authorization sources.

## 18. D-15 — Frontend and bilingual semantics

Studio MAY expose only the approved fields and states after the backend contract passes its
security gates. English is LTR and Arabic is RTL. Canonical IDs, entity types,
classifications, match kinds, revisions, hashes, and service identifiers remain canonical
and LTR where displayed.

Locale SHALL NOT be sent as a search-semantic parameter and SHALL NOT alter normalization,
matching, ordering, cursor behavior, authorization, tenant, classification, or ranking.
Studio SHALL not compute additional matches, retain result objects in credential-like or
persistent browser storage, or infer totals from pagination.

## 19. D-16 — Performance and abuse resistance

All candidate acquisition and continuation queries SHALL be tenant- and revision-scoped and
index-supported. Implementations SHALL bound query size, page size, cursor size, candidate
batches, total candidate work, database statement duration, and concurrent search work using
repository-tested hard maxima. No numeric latency SLO is invented here; ADR-015 and ADR-017
remain authoritative for observability/capacity governance.

Performance tests SHALL use representative tenant cardinalities and worst-case common
prefixes. Query-plan regression tests SHALL fail when approved index paths disappear or when
tenant/revision constraints are not part of the index condition. A low response limit SHALL
never be treated as proof that execution is bounded.

## 20. D-17 — Observability and privacy

Safe telemetry MAY record route template, operation `search`, status class, duration,
effective page-size bucket, continuation boolean, normalizer version, authorized returned
count bucket, candidate-work ceiling reached, and dependency outcome. Metrics labels SHALL be
bounded and low-cardinality.

Browser-visible URLs, default access/reverse-proxy logs, logs, traces, metrics, and error
reports SHALL NOT contain raw/normalized query text, request bodies, query
digest, cursor, result contents, aliases, snippets, tokens, tenant-supplied security context,
or classification-denied candidates. Correlation IDs remain governed by existing middleware.

## 21. D-18 — Failure behavior

| Failure | Required behavior |
| :--- | :--- |
| Authentication/delegation failure | Fail closed; no search execution or results |
| Permission denial | Existing uniform 403 behavior; delegated denial audited |
| Classification evaluation failure | Fail closed; expose no candidates |
| Delegated Audit failure | Fail closed; no unattributed response |
| Malformed, tampered, expired, mismatched cursor | Uniform invalid-continuation error; never restart |
| Pinned revision/search representation unavailable or unverifiable | Fail explicitly; never switch revision |
| PostgreSQL failure | Fail closed with existing dependency-safe error; no Neo4j fallback |
| Malformed, empty, or over-bound query | Reject before database search |
| Candidate work ceiling reached | Fail the whole request with a generic retryable bounded-work error and no partial page, cursor, or counts |

No failure path may retry without tenant scope, downgrade authorization, bypass PolicyEngine,
return partial unauthorized data, or fall back to an unapproved store.

## 22. Search-specific threat model

| Threat | Mitigation |
| :--- | :--- |
| Tenant enumeration/browser tenant injection | Verified-caller tenant only; BFF rejects security-context parameters; tenant leads every index |
| Classified entity enumeration | Existing PolicyEngine gate before response and page construction; absent and denied produce no observable result distinction |
| Alias leakage | Aliases are matching inputs only; matched aliases/snippets are never returned or audited |
| Pagination oracle | No totals/facets; `has_more` requires a further authorized item; cursor stores only last returned authorized position and is encrypted |
| Timing/result-shape leakage | Indexed bounded batches, uniform public errors, no hidden counts; performance tests compare absent and classification-pruned cases |
| Cursor manipulation/replay | Versioned authenticated encryption, tenant/query/revision/endpoint binding, expiry, bounded key rotation, uniform rejection |
| Expensive common-prefix/query abuse | Length/page/work/concurrency/statement bounds plus tenant/revision-leading indexes and plan gates |
| Audit/log/URL leakage of sensitive terms | JSON-body POST; raw/normalized query, request body, digest, cursor, aliases, and results prohibited from default logs, Audit, traces, and telemetry |
| Stale projection disclosure | PostgreSQL revision-bound representation only; Neo4j excluded; unavailable representation fails closed |
| Policy changes between pages | Authorization and classification re-evaluated on every continuation |

Residual timing and page-shape variance cannot be eliminated completely without returning
padding/fabricated results, which is prohibited. Implementations SHALL minimize it through
bounded indexed work and uniform error behavior and SHALL test that denied candidates do not
create direct count/cursor or deterministic error oracles.

## 23. Alternatives considered

### A. Application-memory scan of `MemoryGraph` — rejected

It preserves the current adapter-independent query model but materializes the entire tenant
graph and performs O(N) normalization/matching for each request. Page limits do not bound the
scan. It offers no production query-plan assurance and creates an abuse surface for common
prefixes.

### B. PostgreSQL authoritative indexed search — accepted

It keeps authority, revision history, transactionality, backup/recovery, tenant scoping, and
operational ownership in the existing authoritative boundary. Exact/prefix semantics need
only deterministic normalized keys and B-tree indexes; no search extension is required.

### C. Neo4j candidate search — rejected

Neo4j is a lagging, current-head-only, rebuildable topology projection. Making it candidate
authority would require new Cypher/index, lag, fallback, historical, and authorization-safe
pagination contracts and could disclose stale entities. ADR-024 already rejects direct
Neo4j query execution without a dedicated consistency decision.

### D. Separate derived search projection — rejected initially

A separately updated materialized service/table would introduce lag, checkpoint, rebuild,
read-repair, authorization, and failover semantics. The selected PostgreSQL representation is
derived but transactionally maintained with the authoritative revision, avoiding a second
eventually consistent serving authority.

### E. Elasticsearch/OpenSearch — rejected

It adds infrastructure, credentials, tenant partitioning, indexing lag, backup/recovery,
schema evolution, security filtering, and operational ownership disproportionate to exact
and prefix matching. It is not justified by current evidence or approved architecture.

### F. Semantic/vector search — rejected

Embeddings and approximate similarity are nondeterministic/explainability-sensitive, require
new model and vector-store authority, and risk classification leakage during indexing and
retrieval. No current ADR authorizes them.

## 24. Future extensions explicitly deferred

The following require future architecture review and are not authorized by this ADR:

- fuzzy, edit-distance, phonetic, stemming, transliteration, tokenized, or substring search;
- semantic/vector search, embeddings, approximate nearest-neighbor indexes, or reranking;
- LLM-generated queries, query expansion, summarization, or snippets;
- cross-tenant or platform-wide search;
- facets, aggregations, total counts, hidden counts, or result estimates;
- arbitrary metadata, evidence, history, relationship, owner, or source search;
- external search engines or direct Neo4j search;
- locale-specific backend matching or ordering;
- historical-revision selection by a browser parameter;
- autocomplete/typeahead; and
- numeric relevance scores or opaque ML ranking.

## 25. Implementation acceptance criteria

Implementation is conformant only when automated tests and review prove:

1. tenant A cannot discover tenant B IDs, labels, aliases, classifications, counts, or cursor
   effects;
2. browser tenant/clearance/principal input is rejected and never authoritative;
3. permission and existing PolicyEngine classification pruning occur before exposure and
   page construction;
4. denied existence, alias, classification, counts, and continuation state are absent;
5. mixed pages contain only authorized entities and do not reveal filtered counts;
6. exact/prefix normalization and all six tiers match shared Unicode conformance vectors;
7. unsupported fields, substrings, tokens, metadata, and fuzzy forms do not match;
8. duplicate field/alias matches yield one entity at its best tier;
9. ordering is deterministic by `(tier, node_id)` across adapters and repeated executions;
10. first-page revision pinning and revision-bound continuation are proven across concurrent
    commits;
11. every continuation re-evaluates current authentication, tenant, permission, and
    classification; revoked access takes effect immediately and an unauthorized former
    boundary remains non-observable;
12. invalid, tampered, replayed cross-tenant/query, expired, and unsupported cursors fail
    uniformly;
13. cursor expiry never exceeds pinned-revision/search-representation retention; retirement
    and key rotation cannot cause current-head or cross-revision continuation;
14. cursor plaintext contains no raw query, denied ID, clearance, token, total, or offset;
15. delegated Human Principal and Acting Service attribution are preserved on success,
    denial, and failure;
16. delegated Audit failure remains synchronously fail closed;
17. raw/normalized queries, request bodies, query digests, cursors, aliases, and results are
    absent from browser URLs and default access/proxy logs, logs, traces, metrics, errors,
    correlation metadata, and Audit events;
18. PostgreSQL search rows are transactionally revision-complete, hash-verifiable,
    tenant-scoped, rebuildable, and migration/backfill safe;
19. authoritative write, migration/backfill, rebuild, and query normalization pass identical
    versioned vectors without host-locale or database-collation dependence;
20. representative exact, prefix, and continuation `EXPLAIN` plans use approved indexes and
    include tenant and revision constraints;
21. no Neo4j or external search authority/dependency is introduced;
22. same-origin `/bff/*` remains the only browser path; the narrow POST forwarder enforces
    CSRF, schema/body bounds, fixed upstream routing, and security-context rejection; and no
    browser token/security-context storage or injection is added;
23. empty, malformed, over-length, over-byte, unknown/duplicate-field, over-limit, and expensive
    queries are bounded/rejected;
24. no total, facet, snippet, raw alias, relevance score, or fabricated metadata appears;
25. English/Arabic and LTR/RTL presentation produce identical backend request semantics and
    preserve canonical technical values; and
26. all existing Knowledge Graph, authorization, classification, delegation, Audit,
    persistence, BFF, dependency, and Studio security tests remain green.

## 26. Implementation sequence after acceptance

1. Specify normalization/cursor conformance vectors and API/OpenAPI schemas.
2. Add migration, transactionally maintained representation, backfill/rebuild tooling, and
   query-plan tests.
3. Add application commands/results and pure deterministic search orchestration.
4. Add Knowledge Graph route, delegated-aware authorization, PolicyEngine pruning, bounded
   authorized-page filling, Audit, error mapping, and observability.
5. Verify PostgreSQL integration, concurrency/revision pinning, migration adoption, query
   plans, tenant isolation, classification non-disclosure, cursor cryptography, and Audit
   failure behavior.
6. Add the narrow CSRF-protected delegated Studio BFF search forwarder; do not broaden the
   generic GET proxy or create a general POST proxy.
7. Upgrade Studio in English/Arabic after the backend security suite passes.
8. Run repository dependency, supply-chain, pre-commit, and production-build gates.

No later phase may compensate in UI for a failed backend security or consistency gate.

## 27. Consequences

### Positive

- deterministic, explainable search without opaque ranking;
- PostgreSQL authority and revision consistency remain explicit;
- no stale Neo4j or external-index disclosure path;
- closed searchable-field surface and no totals/facets reduce leakage;
- authorization and classification remain in their existing authoritative components;
- transactionally indexed execution replaces unbounded graph scans; and
- the generic BFF boundary remains unchanged.

### Negative

- authoritative revision commits gain search-representation maintenance cost;
- retained revision-bound search rows increase PostgreSQL storage;
- Unicode normalizer changes require versioned rebuilds;
- authorized page filling may inspect multiple bounded candidate batches; and
- encrypted cursor key lifecycle becomes a new service operational responsibility.

## 28. Approval boundary

While this ADR remains **Proposed**, no implementation is authorized. Acceptance requires a
named Decision Authority and Decision Date in this document and the Architecture Decision
Register. Implementation status SHALL remain **Not started** until code is separately merged
and repository-validated.
