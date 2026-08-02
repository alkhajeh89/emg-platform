# EMG PD-001 — MVP Freeze Control Record

**Status:** Accepted
**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Project Architect
**Decision Date:** 2026-08-03
**Type:** Freeze Control record (L2 Product)
**Governing authority:** `docs/product/EMG_PRODUCT_ARCHITECTURE_FREEZE.md`
(v1.0-FROZEN), §23 and §24; GR-001 Rule 5.
**Baseline:** `develop` at `dd84fa9`.

---

## 1. Decision

**The Product Architecture Freeze is AFFIRMED, not amended.**

**The Executive Dashboard remains OUTSIDE the MVP.**

This record is raised under Freeze Control because the question *"does the
Executive Dashboard enter the MVP?"* was asked. The answer is no, and the
Freeze text is therefore left untouched. **No section of the Freeze is
modified, reordered, reinterpreted, or unfrozen by this record.**

## 2. Scope

This record decides exactly one thing: MVP membership of the Executive
Dashboard. It decides nothing else.

**In scope**

- Whether the Executive Dashboard is part of the frozen MVP.
- Whether placeholder executive metrics may be shown in MVP.

**Non-goals (explicitly not decided here)**

- The dashboard's content — already frozen at Freeze §23 and unchanged.
- The MVP's composition — already frozen at Freeze §24 and unchanged.
- When the dashboard is delivered — sequenced by Freeze §25 (v1.0), not here.
- Any AI, search, workflow, administration, or integration scope.
- Any architecture decision. This record creates none.

## 3. Frozen constraints this record affirms

**FACT.** Freeze §24 states verbatim:

> **Explicitly out of MVP:** multi-tenancy, ABAC/classification enforcement,
> semantic/AI search, **dashboards**, SDKs, on-prem/air-gapped. MVP exists to
> validate value, not to sell to regulated customers.

**FACT.** Freeze §24 defines the MVP web application as exactly four surfaces:
*"Thin web app: graph explorer + decision timeline + evidence viewer + grounded
keyword 'why'."*

**FACT.** Freeze §25 places *"Basic dashboards"* in the v1.0 definition, not the
MVP.

**INFERENCE.** The Freeze already answers this question. This record exists to
make the answer explicit and evidenced, so the question is not re-asked
informally.

## 4. Evidence — the six frozen dashboard indicators

Freeze §23 fixes six content blocks for the Executive Dashboard. Each was
assessed against the repository at `dd84fa9`.

| # | Frozen §23 indicator | Computable today? | Blocking dependency |
| :--- | :--- | :--- | :--- |
| 1 | **"Decisions & why"** — recent decisions with rationale, approver, evidence strength | ❌ **No** | `Decision`, `DecisionRationale`, `Approval` — not modeled (`emg-ontology/references.py:10-12`, deferred to EPIC-08). Addressed by ADR-037 |
| 2 | **Decision-to-outcome lineage** — trace a decision forward to its consequences | ❌ **No** | Same. The `RESULTED_IN` edge exists in the frozen vocabulary, but there is no governed `Decision` entity to traverse from |
| 3 | **Institutional-memory coverage** — % of decisions with documented rationale/evidence | ❌ **No** | Same. There is no `Decision` population, so the denominator does not exist |
| 4 | **Knowledge-loss risk** — decisions owned by departing/departed people lacking documentation | ❌ **No** | Same, **plus** an HR/leaver signal. **No such data source exists anywhere in the repository and none is required by any accepted ADR** |
| 5 | **Risk & policy exposure** — risks flowing from active policies | ❌ **No** | Same, plus Policy and Risk entities |
| 6 | **Audit & compliance posture** — evidence completeness, classification distribution | ⚠️ **Partial** | Classification distribution is derivable from audit events and the graph. Evidence *completeness* is not, absent a `Decision` population |

**Summary of evidence.** Five of six indicators are strictly non-computable.
The sixth is half-computable. One (indicator 4) is blocked on a data source
that does not exist in the platform at all.

## 5. Prohibition — no placeholder executive metrics

**This is a binding prohibition, not guidance.**

For the duration of the MVP, the product **must not** display, mock, seed,
estimate, extrapolate, or otherwise fabricate any Freeze §23 executive
indicator. Specifically prohibited in MVP:

- Hard-coded, sample, or demo values for any of the six indicators.
- Charts or figures rendered from synthetic or seeded decision data.
- Percentages, coverage scores, or risk counts computed over an incomplete or
  proxy population.
- "Illustrative" or "preview" dashboards, including behind a feature flag, in a
  demo environment, or in sales material generated from the product.
- Any indicator labelled as real that is not derived from governed, evidence-
  linked, classification-filtered data.

**Rationale.** EMG's central product claim is that AI and analytics are
grounded consumers of evidence and never the source of truth (Freeze §1;
`EMG_PRODUCT_VISION.md`). An executive indicator that is not derived from
governed evidence contradicts the product's own promise on the surface most
visible to buyers. A fabricated governance metric is a governance defect.

**Permitted.** Design artifacts (wireframes, Figma files, slides) may depict the
dashboard as a *future* surface provided they are clearly marked as not
implemented and are not generated from the running product.

## 6. Consequences

**Positive**

- The MVP remains provable end-to-end against already-implemented, already-
  secured APIs.
- No executive is ever shown a fabricated indicator.
- The dashboard becomes genuinely computable at v1.0 once ADR-037 is
  implemented, exactly as Freeze §25 sequences it.
- The Freeze retains its authority: a scope question was raised, evidenced, and
  answered without eroding the frozen baseline.

**Negative — accepted**

- The most commercially persuasive surface is unavailable for early
  demonstration. **Mitigation:** the MVP's Evidence Viewer and Decision Timeline
  demonstrate the actual differentiator — provable lineage and immutable
  evidence — more convincingly than an unpopulated dashboard would.
- Executive stakeholders must be told the dashboard is deliberately sequenced,
  not omitted. This record is the artifact for that conversation.

**Neutral**

- No engineering work is created or cancelled by this record.

## 7. Acceptance criteria

- **AC-1.** This record states that the Freeze is affirmed and not amended, and
  no Freeze section is modified.
- **AC-2.** No MVP artifact — screen, wireframe, backlog item, or acceptance
  test — contains an Executive Dashboard.
- **AC-3.** All six Freeze §23 indicators are recorded with an explicit
  computability status and a named blocking dependency.
- **AC-4.** The placeholder-metric prohibition in §5 is enforceable: any MVP
  artifact displaying a §23 indicator fails review.
- **AC-5.** The dashboard's re-entry path is unambiguous — it becomes eligible
  when ADR-037 is implemented and Freeze §25 (v1.0) is entered.

## 8. Related

- `docs/product/EMG_PRODUCT_ARCHITECTURE_FREEZE.md` §23, §24, §25
- `docs/architecture/EMG_ADR-037_DECISION_DOMAIN_MODEL.md` (unblocks indicators
  1, 2, 3, 5 and completes 6)
- `docs/governance/GR-001_EMG_DOCUMENTATION_GOVERNANCE_FRAMEWORK.md` Rule 5
