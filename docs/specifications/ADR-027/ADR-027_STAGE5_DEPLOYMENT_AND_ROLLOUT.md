# ADR-027 Revision 5 — Stage 5 Deployment and Rollout

**Layer:** L4 delivery documentation
**Governing authority:** ADR-027 Revision 5, Stage 5. Product scope is governed
by `docs/product/EMG_PRODUCT_ARCHITECTURE_FREEZE.md`; architecture by accepted
ADRs; documentation authority by GR-001.
**Status:** Documentation of existing requirements. Creates no capability and
claims no production readiness.
**Baseline:** `develop` at Stage 4 completion.

## 1. Accepted scope

ADR-027 Revision 5 defines Stage 5 as: "Deployment documentation and rollout.
Document the new role/policy-rule requirements, following the same 'identity
provisioning requirement' pattern ADR-026 §14/Part E already established."

This document does exactly that and nothing else. It adds no route, command,
DTO, schema, migration, or configuration surface, and amends no accepted ADR.

## 2. Authoritative mutation surface

Exactly five routes, unchanged since Phase 4A:

| Operation | Method | Route | Policy resource | Action |
| :--- | :--- | :--- | :--- | :--- |
| Create Entity | POST | `/api/v1/entities` | `knowledge-graph.entity` | `create` |
| Replace Entity | PUT | `/api/v1/entities/{entity_id}` | `knowledge-graph.entity` | `update`, `retire`, `restore`, `reclassify` |
| Merge Entities | POST | `/api/v1/entities/{survivor_id}/merge` | `knowledge-graph.entity` | `merge` |
| Replace Relationship | PUT | `/api/v1/relationships/{edge_id}` | `knowledge-graph.relationship` | `update` |
| Close Relationship | POST | `/api/v1/relationships/{edge_id}/close` | `knowledge-graph.relationship` | `retire` |

No batch route, Create Relationship route, or standalone Retire Entity route
exists or is authorized.

## 3. Role provisioning requirement

Two realm roles govern the mutation surface:

- `knowledge-steward` — human callers.
- `svc-knowledge-graph-writer` — the Knowledge Graph writer service client.

The end-to-end path each role must travel, following ADR-026 Part E:

- **Service callers:** realm role grant → `realm_access.roles` in the issued
  access token → `TenantServiceTokenValidator` role extraction
  (`emg_knowledge_graph_api/authn.py`) → `ServicePrincipal.roles` →
  `PolicyRule.required_roles` matching in `emg_policy_engine`.
- **Future human callers:** when separately implemented under ADR-025 §8.9, the
  human role path is expected to carry the `knowledge-steward` realm role
  through the approved human identity flow into `Principal.roles`, and then
  into `PolicyRule.required_roles` evaluation. No human authentication path for
  the Knowledge Graph API is implemented or authorized by this Stage 5
  document.

A deployment that does not provision the required realm roles and grants cannot
satisfy the accepted mutation authorization model. Depending on the missing
role or claim, the caller may be rejected during service-token validation or
authenticated and subsequently denied by policy. The exact fail-closed outcome
must be verified during rollout validation.

**Repository-verified provisioning divergence.** `tools/seed-data/keycloak/emg-realm.json`
defines all nine realm roles, including `knowledge-steward` and
`svc-knowledge-graph-writer`, and six users.
`docker/keycloak/import/emg-realm.json` defines only `admin` and `user` and no
users. A deployment seeded from the latter satisfies no mutation policy rule.
This document records that divergence; reconciling the artefacts is
configuration work outside Stage 5.

## 4. Policy-rule provisioning requirement

`EMG_KNOWLEDGE_GRAPH_API_POLICY_CONFIG_PATH` must point at a deployed
`emg_policy_engine.PolicyConfig` file containing the mutation rules shipped in
`services/knowledge-graph/config/policy.example.yaml`:

| Rule | Action | Required role |
| :--- | :--- | :--- |
| `kg-entity-create` | `create` | `knowledge-steward` or `svc-knowledge-graph-writer` |
| `kg-entity-update-human` | `update` | `knowledge-steward` |
| `kg-entity-update-service-owner` | `update` | `svc-knowledge-graph-writer`, with `owner_matches_principal` |
| `kg-entity-retire-human` | `retire` | `knowledge-steward` |
| `kg-entity-retire-service-owner` | `retire` | `svc-knowledge-graph-writer`, with `owner_matches_principal` |
| `kg-entity-restore-human` | `restore` | `knowledge-steward` |
| `kg-entity-merge-human` | `merge` | `knowledge-steward` |
| `kg-entity-reclassify-human` | `reclassify` | `knowledge-steward` |
| `kg-relationship-update-human` / `-service-owner` | `update` | as above |
| `kg-relationship-retire-human` / `-service-owner` | `retire` | as above |

The accompanying clearance-deny rules must be deployed with them. The approved
mutation-policy set must be deployed and reviewed as a complete configuration.
Individual rules must not be removed or altered without re-validating the
authorization and classification behaviour against the accepted ADRs.

## 5. Human-only operations

Restore, Merge, and Reclassify are restricted to `knowledge-steward` by
`kg-entity-restore-human`, `kg-entity-merge-human`, and
`kg-entity-reclassify-human`. `services/knowledge-graph/tests/test_authz_scenarios.py`
asserts `expected_outcome="deny"` for the writer service principal against all
three actions. They are therefore unreachable for the service callers that
exist today. Human authentication remains future work under ADR-025 §8.9;
see OBS-A-005 in the Architecture Decision Register.

## 6. Token claim provisioning requirement

| Claim | Required | Behaviour when absent or invalid |
| :--- | :--- | :--- |
| RS256 signature, `iss`, `aud`, `exp`, `iat` | Yes | Request rejected |
| `azp` / `client_id` in the recognized set | Yes | Request rejected |
| `realm_access.roles` containing the client's registered roles | Yes | Request rejected |
| `tenant_id` (`EMG_KNOWLEDGE_GRAPH_API_TENANT_CLAIM`) | Yes | Request rejected |
| `classification_clearance` | No | Resolves to `UNCLASSIFIED` |

Two distinct fail-closed behaviours apply. Signature, issuer, audience,
expiry, client identity, registered roles, and tenant claim reject the request.
The clearance claim degrades instead: a missing, non-string, or unrecognized
value resolves to `UNCLASSIFIED`, which satisfies no mutation allow rule
requiring a higher clearance. A deployment that omits clearance issuance
therefore produces callers that authenticate and are denied every mutation,
without any authentication error — the same silent failure ADR-026 Part E
describes for classification enforcement.

## 7. Startup requirements

The service loads and validates the schema catalog at
`EMG_KNOWLEDGE_GRAPH_API_SCHEMA_CATALOG_PATH`, runs the normalizer boot gate,
and fails before serving traffic if the artefact is missing, malformed, or
inconsistent. Production never falls back to the unconfigured placeholder.

Database roles follow ADR-034: `emg_knowledge_graph_migrator` owns schema
objects; `emg_knowledge_graph_app` holds only the DML the runtime requires.
Migrations V003 (`mutation_idempotency`), V004 (`mutation_ledger`), and V005
(runtime least privilege) must be applied.

## 8. Rollout and rollback

ADR-027 Revision 5 states: "a pure code/config revert at any stage — no
persisted state depends on this ADR's mechanism; every commit it produces is an
ordinary revision, readable and diffable by the existing, unchanged
read/history API regardless of whether the Mutation API is later disabled. The
`mutation_idempotency` table, if rolled back, simply stops being consulted — it
holds no state any other subsystem depends on."

This document adds no rollback mechanism beyond that accepted statement.

## 9. Non-production rollout validation

Verification of already-shipped behaviour. No new capability:

1. The imported realm defines and grants `knowledge-steward` and
   `svc-knowledge-graph-writer`, and issues `tenant_id` and
   `classification_clearance`.
2. `/readyz` reports the schema catalog loaded and the placeholder inactive.
3. A `svc-knowledge-graph-writer` token succeeds on Create Entity and is denied
   on Restore, Merge, and Reclassify.
4. A token missing `tenant_id` is rejected.
5. A token without `classification_clearance` authenticates and is denied
   mutations requiring a higher clearance.

## 10. Production prerequisites — outside Stage 5

Recorded as requirements, not performed here:

1. Production realm role provisioning for `knowledge-steward` and
   `svc-knowledge-graph-writer`.
2. `classification_clearance` claim issuance for both caller kinds.
3. Production policy approval and deployment.
4. Production tenant and clearance assignment.
5. `emg_knowledge_graph_migrator` / `emg_knowledge_graph_app` DSN provisioning.
6. Application of migrations V003, V004, and V005.
7. Schema catalog artefact provisioning and path configuration.
8. Idempotency retention and whole-transaction timeout value decisions.
9. Target environment selection.
10. Deployment and rollback rehearsal.
11. Support and on-call ownership assignment.
12. Reconcile the broader platform-wide client-registry and production
    provisioning follow-up recorded in the Production Readiness Roadmap; the
    Knowledge Graph API already enforces its local `_RECOGNIZED_CLIENTS`
    allow-list.

## 11. Explicitly outside Stage 5

No sixth route of any kind, including batch, Create Relationship, or standalone
Retire Entity · no new command or DTO · no UI · no schema discovery (T-A-002)
· no durable effective-schema-version persistence (T-A-003) · no
mutation-ledger query capability · no ADR-033 Phase 4 work · no metrics
backend, dashboards, tracing, or alerting (ADR-015 / FEAT-12-3) · no IaC, HA/DR,
or secrets-platform implementation · no ADR-028 audit delivery · no amendment to
any accepted ADR.

**This document claims no production readiness.**
