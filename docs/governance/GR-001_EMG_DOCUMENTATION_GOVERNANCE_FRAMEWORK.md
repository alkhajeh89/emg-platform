# GR-001 — EMG Documentation Governance Framework

**Document type:** Governance Document — not an Architecture Decision Record
(ADR)
**Resolution:** Board Resolution GR-001
**Status:** Ratified and Effective
**Effective Date:** 2026-08-01
**Joint approval:** Office of the CTO and Architecture Board
**Scope:** Documentation authority, classification, precedence, and conflict
resolution only

---

## 1. Purpose and Scope

GR-001 establishes the canonical governance framework for documentation in
`docs/`. It determines what kind of authority a document may carry, which
artifact governs a disputed subject, and how documentation conflicts are
resolved.

GR-001 does **not**:

- define or change product scope;
- unfreeze, amend, or supersede the Product Architecture Freeze;
- create, accept, revise, or supersede an ADR;
- define technical architecture, implementation semantics, or delivery scope;
- govern day-to-day operating conduct, workflow, communication, or
  implementation procedure; or
- create Executive Vision content.

GR-001 is a governance document, not an ADR. Its authority is
subject-scoped to documentation governance.

## 2. Subject-Scoped Authority Principle

EMG documentation authority is **subject-scoped, not based on a universal
top-to-bottom document ranking**. A document controls only the subject for
which it has been approved:

- GR-001, at L0, governs documentation authority and conflict precedence.
- Ratified L1 executive direction governs executive strategy within its stated
  scope.
- The L2 Product Architecture Freeze governs product scope and product
  boundaries.
- Accepted L3 ADRs govern architecture within their stated scope.
- L4 delivery, support, reference, and operating records govern delegated
  detail, execution evidence, and conduct only;
  they cannot create product or architecture authority.

A document from one subject does not override the governing authority for
another subject merely because it has a higher layer number, a later date, a
more prominent directory, or a more forceful title.

## 3. Ratified Five-Layer Framework

Layer classification describes a document's intended function. It does not
replace the document's approval status, owner, effective date, or stated
scope.

| Layer | Name | Definition | Authority boundary |
| :--- | :--- | :--- | :--- |
| **L0** | Documentation Governance | GR-001 and any future jointly ratified documentation-governance controls. | Governs documentation authority, classification, and conflict precedence only. It does not define executive strategy, product scope, architecture, or operating conduct. |
| **L1** | Executive Vision and Direction | Ratified enterprise intent, strategic outcomes, investment direction, risk appetite, and Board or executive decisions. | Governs executive strategy only. It does not create product scope or technical architecture unless the corresponding L2 or L3 authority is separately changed. |
| **L2** | Product Architecture Freeze | The frozen product definition, product boundaries, editions, personas, deployment models, and release scope. | The Product Architecture Freeze is authoritative for product scope. Narrative product material cannot override the Freeze. |
| **L3** | Accepted Architecture Decisions | Accepted ADRs and other architecture artifacts explicitly approved by the Architecture Board within their stated scope. | Only accepted architecture decisions are binding. Proposed, draft, review, analysis, register, specification, or implementation-plan material is not accepted architecture. |
| **L4** | Delivery, Support, Operations, Evidence, and Reference | Standards, specifications, plans, backlogs, phase and sprint records, status reports, implementation guidance, runbooks, workflows, reviews, indexes, AI context, and descriptive engineering documentation. | May govern delegated detail or operating conduct and record delivery facts within its scope. It cannot create or override L0–L3 authority. |

### 3.1 Executive Layer Definition

L1 contains executive or Board material only when its status and approving
authority show that it is ratified. Executive summaries, presentations,
roadmaps, registers, and narrative documents that are merely descriptive,
draft, declared, or awaiting decision remain non-binding until the named
executive authority approves them.

L1 does not acquire authority over product scope or architecture by
implication. A strategic direction that requires a product-scope or
architecture change must be followed by the applicable L2 freeze-control or
L3 ADR process.

### 3.2 Product Layer Definition

L2 governs what EMG is, its product boundaries, editions, target users,
deployment models, and release definitions. The canonical L2 authority is:

- `docs/product/EMG_PRODUCT_ARCHITECTURE_FREEZE.md`.

`docs/product/EMG_PRODUCT_VISION.md` is product narrative and context. Where
it differs from the Freeze, the Freeze governs product scope. GR-001 does not
unfreeze or modify either document; any Freeze change still requires its own
explicit unfreeze decision and version bump.

## 4. Authority Matrix

| Subject | Governing authority | Layer | Approval/status required | Subordinate material |
| :--- | :--- | :--- | :--- | :--- |
| Documentation classification and precedence | GR-001 | L0 | Joint approval by the Office of the CTO and Architecture Board; effective status | All repository documentation |
| Executive strategy and enterprise direction | Ratified executive or Board decision | L1 | Named executive/Board approval | Executive summaries, presentations, narrative roadmaps, and declared register items |
| Product scope and boundaries | `EMG_PRODUCT_ARCHITECTURE_FREEZE.md` | L2 | `FROZEN`, subject to its Freeze Control | Product Vision, executive product narratives, roadmaps, backlogs, and delivery records |
| Technical architecture | Accepted ADR or explicitly Board-approved architecture baseline within its stated scope | L3 | `Accepted` or equivalent explicit Architecture Board approval | Reference architectures, reviews, options, implementation plans, specifications, and engineering documents |
| Standard, policy, or specification detail | Applicable L4 artifact acting within an explicit L2/L3 delegation | L4 | Named owner and approval/effective status appropriate to its purpose | Draft standards, examples, guides, and conformance evidence |
| Delivery sequence, operating conduct, and implementation evidence | Applicable approved plan or protocol | L4 | Status appropriate to its operational purpose | Sprint/phase records, implementation reports, status pages, runbooks, and workflows |
| Current implementation fact | Repository evidence, tests, and generated or verified status records | L4 evidence | Verifiable against the repository | Narrative claims that have drifted from implementation |
| Historical material | `docs/archive/` | Non-governing | None | All archived descendants |

## 5. Twelve Governance Rules

1. **Authority is subject-scoped.** Resolve each statement according to its
   subject; do not apply a blanket document hierarchy across unrelated
   subjects.
2. **Approval status is mandatory.** A title, filename, directory, register
   entry, or date does not make a document authoritative. Required approval
   and status must be explicit.
3. **Placement does not confer authority.** A document under
   `docs/architecture/` is not an accepted ADR merely because of its
   location, and a file named `DECISION` is not binding without the required
   approval.
4. **GR-001 is limited to documentation governance.** It cannot redefine
   product scope, architecture, standards content, implementation semantics,
   or operating conduct.
5. **The Product Freeze controls product scope.** Product narrative,
   executive material, roadmaps, specifications, and delivery records must
   conform to the Freeze on product subjects.
6. **Accepted ADRs control architecture.** Draft, proposed, reference,
   review, analysis, support, and implementation documents cannot override an
   accepted ADR within its scope.
7. **L4 derivation must be delegated and traceable.** A standard,
   specification, policy, or conformance document must identify its governing
   L2/L3 basis, owner, status, and scope. It remains L4 and cannot amend that
   governing authority.
8. **L4 cannot create product or architecture decisions.** Plans, protocols,
   backlogs, status reports, phase/sprint records, guides, and source-adjacent
   documentation may describe or operationalize decisions but may not invent
   them.
9. **Archived material is non-governing.** Nothing under `docs/archive/`
   may be used to override a current governing artifact.
10. **Supersession must be explicit.** A later date or revision number wins
    only when the same competent authority explicitly supersedes the earlier
    artifact for the same subject and scope.
11. **Traceability is required.** Derived documents must cite their governing
    authority; documents that mix subjects must identify the authority for
    each normative statement.
12. **Unresolved conflicts fail closed.** When the process in Section 6 does
    not yield one governing statement, record the conflict and escalate it to
    the competent authority. Do not implement or silently reconcile the
    disputed requirement.

## 6. Deterministic Conflict-Resolution Process

Apply these steps in order:

1. **Isolate the conflict.** Quote or identify the exact competing statements
   and the scope in which they differ.
2. **Classify the subject.** Assign the conflict to documentation governance,
   executive direction, product scope, architecture, delegated
   standard/specification detail, delivery/operations, implementation fact,
   or historical material.
3. **Verify each artifact.** Record its owner, approval status, effective
   date, revision, stated scope, and any explicit supersession clause.
4. **Select the competent authority from the matrix.** GR-001 governs
   documentation precedence; the Product Freeze governs product scope;
   accepted ADRs govern architecture; L4 artifacts govern only delegated
   detail or their operating and evidentiary scope.
5. **Discard non-governing candidates.** Ignore archived material, drafts,
   proposals, unaccepted decisions, and lower-authority material for the
   disputed subject.
6. **Resolve same-authority conflicts.** Apply an explicit supersession
   clause first. If none exists, use the later effective revision only when
   it was approved by the same competent authority for the same subject and
   scope.
7. **Check cross-subject effects.** A valid decision on one subject cannot
   silently change another. For example, executive direction that changes
   product scope requires the Freeze process, and a specification that
   changes architecture requires an ADR.
8. **Escalate ambiguity.** If two competent artifacts still conflict, stop
   the affected work and refer the conflict to the authority responsible for
   that subject. No document may infer the missing decision.
9. **Record the outcome.** Update the relevant register or status/index
   material with the governing artifact, resolution date, and any required
   follow-up. Do not rewrite historical evidence to conceal the conflict.

## 7. Relationship with ADRs

- GR-001 is a Governance Document, not an ADR.
- GR-001 governs how documentation authority is classified and conflicts are
  resolved. It does not make an architecture decision.
- Accepted ADRs are L3 Architecture Authority within their stated scope.
- An ADR is binding only when its own status and approving authority identify
  it as accepted.
- Proposed or draft ADRs, ADR implementation plans, reviews, design packages,
  architecture-support documents, and register entries do not become accepted
  architecture by association.
- Accepted ADRs remain authoritative for their architectural subjects and
  cannot be amended by GR-001 or L4 material.
- If documentation governance itself requires change, revise GR-001 through
  its joint governance authority. If technical architecture requires change,
  use the ADR process.

## 8. Canonical Repository-Documentation Assignment — C-1

### 8.1 Coverage Method

Assignments below are recursive. The longest matching path controls; an
explicit file or document-type rule overrides a directory default. A
directory assignment covers every current Markdown file and incidental
metadata file below it. Incidental files such as `.DS_Store` carry no
documentation authority.

Any future path not covered by this table must be classified before it is
merged. It does not inherit authority merely from a similar name.

### 8.2 Canonical Assignment Table

| Path | Assignment | Canonical function and boundary |
| :--- | :--- | :--- |
| `docs/` | L4 root/index container | Contains the documentation index and repository-structure guide; no independent normative authority. |
| `docs/README.md` | L4 | Documentation discovery index. |
| `docs/repo-structure.md` | L4 | Descriptive repository engineering structure; subordinate to the Product Freeze and accepted ADRs. |
| `docs/governance/` | L0 | Contains GR-001. No second governance framework or register is authorized by this assignment. |
| `docs/ai-context/` | L4 | AI orientation and context only. It cannot acquire product or architecture authority or override governing documents. |
| `docs/archive/` | **Non-governing historical material** | Entire subtree is retained only for provenance and history. |
| `docs/archive/architecture/` | **Non-governing historical material** | Archived architecture history; never current authority. |
| `docs/archive/architecture/v1/` | **Non-governing historical material** | Archived v1 package; never current authority. |
| `docs/archive/pre-implementation/` | **Non-governing historical material** | Pre-implementation history; never current authority. |
| `docs/archive/pre-implementation/modules/` | **Non-governing historical material** | Archived module material; never current authority. |
| `docs/architecture/` | L4 by default; L3 only for accepted ADRs | Status, registers, plans, reviews, analyses, backlogs, roadmaps, and support material are L4 unless an explicit row below applies. Placement alone confers no authority. |
| Accepted ADR documents in `docs/architecture/` | L3 | Binding only when the document itself is explicitly Accepted; scope is limited to that ADR. Proposed/draft ADRs remain non-binding proposals. |
| `docs/architecture/backend/` | L4 | Architecture-support and conformance material under the C-2 boundary; not accepted ADRs. |
| `docs/architecture/reference/` | L4 | Reference architecture subordinate to the Product Freeze and accepted ADRs; approval status remains document-specific. |
| `docs/architecture/reference/api/` | L4 | API reference/specification support; subordinate to accepted ADRs. |
| `docs/architecture/reference/data/` | L4 | Data reference architecture; subordinate to accepted ADRs. |
| `docs/architecture/reference/enterprise/` | L4 | Enterprise reference architecture; subordinate to accepted ADRs. |
| `docs/architecture/reference/system/` | L4 | System reference architecture; subordinate to accepted ADRs. |
| `docs/architecture/reference/ux/` | L4 | UX reference architecture; subordinate to accepted ADRs. |
| `docs/architecture/reviews/` | L4 | Review evidence and recommendations; not architecture authority. |
| `docs/backend/` | L4 | Descriptive backend engineering documentation under the C-2 boundary. |
| `docs/backend/implementation/` | L4 | Backend implementation guidance and descriptive technical records. |
| `docs/devops/` | L4 | DevOps standards, guides, pipeline descriptions, registers, and operations material; subordinate to the Product Freeze and accepted ADRs. |
| `docs/engineering/` | L4 | Engineering guidance, design records, implementation notes, status, debt, and testing material; cannot establish product scope or architecture. |
| `docs/enterprise-design/` | L4 | Derived UX/design-system specifications, subordinate to L2 and accepted presentation/UX ADRs. |
| `docs/executive/` | L1 subject to document status | Executive communication and decision material. Only explicitly ratified items govern executive strategy; this assignment creates no new Executive Vision. |
| `docs/frontend/` | L4 | Frontend engineering/reference hub; subordinate to product scope and accepted presentation architecture. |
| `docs/frontend/architecture/` | L4 | Derived frontend architecture specifications; cannot override accepted ADRs. |
| `docs/frontend/components/` | L4 | Component specifications derived from approved product and presentation architecture. |
| `docs/frontend/decisions/` | L4 | Local decision records; not ADRs and not architecture authority unless separately ratified through the ADR process. |
| `docs/frontend/design/` | L4 | Derived frontend design specifications. |
| `docs/frontend/design-system/` | L4 | Design-system standards, subordinate to product and accepted architecture. |
| `docs/frontend/engineering/` | L4 | Frontend engineering practices and implementation guidance. |
| `docs/frontend/features/` | L4 | Feature/interface specifications within already-approved product scope; cannot create new scope. |
| `docs/frontend/governance/` | L4 | Frontend-domain operating and quality processes. The directory name does not grant cross-repository governance authority. |
| `docs/frontend/operations/` | L4 | Frontend operational and release procedures. |
| `docs/frontend/roadmap/` | L4 | Frontend planning material; non-authoritative for product scope. |
| `docs/frontend/screens/` | L4 | Screen specifications derived from approved product/presentation authority. |
| `docs/frontend/sprints/` | L4 | Frontend delivery records; non-authoritative for product scope or architecture. |
| `docs/frontend/user-experience/` | L4 | Derived user-experience specifications, subordinate to product and accepted UX/presentation architecture. |
| `docs/infrastructure/` | L4 | Infrastructure standards, designs, guides, operations, and registers; accepted ADRs remain controlling. |
| `docs/phases/` | L4 | Delivery planning and evidence only; non-authoritative for product scope or architecture. |
| `docs/phases/phase-0/` | L4 | Phase delivery/completion record; non-authoritative for product scope or architecture. |
| `docs/phases/phase-1/` | L4 | Phase plans and completion records; non-authoritative for product scope or architecture. |
| `docs/phases/phase-2/` | L4 | Phase architecture-support, plan, rules, understanding, and completion records; cannot override accepted ADRs. |
| `docs/product/` | L2 subject to document status | Product authority tree. The Product Freeze governs scope; Product Vision is subordinate narrative. |
| `docs/security/` | L4 | Security architecture descriptions, standards, guides, registers, and compliance material; accepted security ADRs remain controlling. |
| `docs/specifications/` | L4 | Specifications and conformance packages derived from L2/L3; placement alone does not approve them. |
| `docs/specifications/ADR-033/` | L4 | ADR-derived conformance/specification material; cannot amend ADR-033 or another accepted ADR. |
| `docs/sprints/` | L4 | Delivery records only; non-authoritative for product scope or architecture. |
| `docs/sprints/proposals/` | L4 | Sprint proposals; delivery planning only. |
| `docs/sprints/reviews/` | L4 | Sprint review evidence and remediation reports. |
| `docs/sprints/status/` | L4 | Sprint status and acceptance evidence. |
| `docs/workflows/` | L4 | Operating and delivery documentation; cannot govern documentation precedence. |

### 8.3 C-1 Verification

At ratification verification, `docs/` contained 49 pre-existing
subdirectories plus the newly created `docs/governance/` directory, for
50 assigned subdirectories in total. It contained exactly two root-level
files, `docs/README.md` and `docs/repo-structure.md`, both assigned
above. The recursive and longest-match rules assign every current descendant.
No current documentation path remains unassigned.

**C-1 status:** Satisfied.

## 9. Backend Documentation Boundary — C-2

The relationship between the two backend documentation trees is:

- `docs/backend/` is descriptive **L4 engineering documentation** unless
  a file explicitly identifies an accepted ADR as the authority for a
  statement. Such a citation makes the ADR authoritative; it does not promote
  the citing file to an ADR.
- `docs/architecture/backend/` is **L4 architecture-support and
  conformance material**. Placement under `docs/architecture/` does not
  make any file an accepted ADR.
- Neither tree may override an accepted ADR.
- Any architectural statement in either tree is subordinate to accepted ADRs
  and must be corrected or escalated when it conflicts with one.
- GR-001 establishes this boundary without rewriting the existing contents of
  either tree.

**C-2 status:** Satisfied.

## 10. Operating-Protocol Boundary — C-3

`docs/architecture/PROMPT_TEMPLATE_POST_ADR026.md` is assigned to **L4**
as the repository operating and implementation protocol.

The two-way boundary is:

- GR-001 governs documentation authority and conflict precedence.
- `PROMPT_TEMPLATE_POST_ADR026.md` governs operating conduct, workflow,
  communication, and implementation protocol.
- GR-001 does not govern day-to-day operating conduct.
- The protocol does not govern documentation precedence and cannot override
  GR-001, the Product Freeze, or accepted ADRs on their respective subjects.

The protocol receives only the smallest boundary declaration required to
remove its competing precedence claim; its operational rules are otherwise
unchanged.

**C-3 status:** Satisfied.

## 11. Board Resolution GR-001

The Office of the CTO and Architecture Board jointly resolve that:

1. the five-layer framework, subject-scoped authority principle, authority
   matrix, governance rules, and conflict-resolution process in this document
   are ratified;
2. GR-001 governs documentation authority only and does not redefine product
   scope or architecture;
3. GR-001 does not amend the Product Architecture Freeze or any accepted ADR;
4. the canonical assignment in Section 8 satisfies C-1;
5. the backend-tree boundary in Section 9 satisfies C-2; and
6. the operating-protocol boundary in Section 10, together with the minimal
   protocol declaration, satisfies C-3.

### 11.1 Conditions Precedent and Effectiveness Record

**Initial ratification status:** “Ratified — effective after verified
satisfaction of C-1, C-2, and C-3.”

| Condition | Required result | Verification evidence | Status |
| :--- | :--- | :--- | :--- |
| C-1 | Assign every current documentation path canonically | Section 8 inventory, assignment table, and coverage rule | **Satisfied** |
| C-2 | Resolve `docs/backend/` versus `docs/architecture/backend/` | Section 9 explicit subordinate L4 boundary | **Satisfied** |
| C-3 | Assign and bound the post-ADR-026 protocol | Section 10 and the minimal declaration in `PROMPT_TEMPLATE_POST_ADR026.md` | **Satisfied** |

All three conditions precedent are demonstrably satisfied by this
documentation change.

**Current status:** Ratified and Effective.

**Effective Date:** 2026-08-01.

**Approved jointly by:** Office of the CTO and Architecture Board.

---

## 12. Change Control

Changes to documentation authority, layer definitions, assignment rules, or
conflict precedence require a revision to GR-001 jointly approved by the
Office of the CTO and Architecture Board. Changes to product scope continue
to use the Product Freeze's control process. Changes to architecture continue
to use the ADR process.
