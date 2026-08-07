# EMG Visual Identity Decision

**Status:** Accepted
**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Design System Governance Authority
**Decision Date:** 2026-08-03
**Type:** L4 design decision, derived from ADR-014
**Baseline:** `develop` at `866d0f7`
**Canonical parent:** `EMG_DESIGN_SYSTEM_BASELINE.md`

> **Scope.** This record selects a **visual character direction** only. It
> introduces no logo, no marketing identity, no illustration system, and no
> final colour values. It expands no product scope.

---

## 1. Context

**FACT.** At `866d0f7` the repository contained **no visual identity of any
kind**: no logo, no brand asset, no SVG, and **zero hex colour values** anywhere
in `docs/frontend/` or `docs/enterprise-design/`. `DESIGN_TOKENS.md` closed with
*"All specific token names and their underlying values are currently TBD."*

Visual identity was therefore genuinely open — not under-documented, but
undecided. Three bounded options were assessed against EMG's actual constraints
rather than aesthetic preference.

## 2. Decision

### **Institutional Neutral is Accepted.**

A restrained, archival, evidence-first visual character. Near-neutral surfaces
with a single deep accent.

**Distinctiveness comes from typography and information density, not chrome.**

## 3. Options assessed

### Option A — Institutional Neutral — **ACCEPTED**

Restrained, document-like, archival. Near-neutral greys with one deep accent
(deep blue or slate-teal).

- **Fits:** a system of record for government, regulated, and audit-facing use.
- **Classification headroom:** ✅ **Excellent** — a neutral base leaves the full
  colour range free for the exclusive classification family.
- **Trade-off, accepted:** least immediately distinctive; risks reading as
  generic if typography is weak. **Mitigation:** distinctiveness is deliberately
  assigned to the dual-script type pairing and to information density.

### Option B — Intelligence Dark-First — **Rejected**

Analyst-console character. Dark surface primary, light theme secondary,
saturated accents for graph and state.

- **Attraction:** suits long analyst sessions and graph traversal.
- **Rejected because:** dark-first complicates evidence print and export
  legibility — a first-order concern for a platform whose Auditor persona
  requires exportable evidence chains (Freeze §4). Saturated accents **compete
  with the classification range**, reducing headroom. Higher accessibility risk
  across contrast pairs.

### Option C — Civic Warm — **Rejected**

Warm neutrals with a muted earth accent; public-sector approachability.

- **Attraction:** broad government accessibility and approachability.
- **Rejected because:** warm palettes overlap conventional warning and
  restricted-classification signalling, **narrowing the safe classification
  range**. May read as informal in defence and regulated contexts, where the
  product's credibility claim is trustworthiness.

## 4. Classification-headroom rationale — the deciding factor

EMG's hardest visual constraint is that
`color.classification.{unclassified, internal, confidential, secret}` is an
**exclusive** token range: no status, chart, action, decorative, or brand token
may draw from it (`EMG_DESIGN_SYSTEM_BASELINE.md` §6.1).

Any identity that consumes saturated colour for brand or state purposes competes
directly with that reserved range. Institutional Neutral consumes the least
colour, and therefore preserves the most headroom for the one visual signal the
platform cannot compromise.

This was the deciding factor. It outweighed distinctiveness.

## 5. No logo, no marketing brand

**Explicitly not decided and not to be invented:**

- No logo or wordmark.
- No marketing brand system, brand guidelines, or campaign identity.
- No illustration style, mascot, or photographic direction.
- No final colour hex values — token **roles** are fixed
  (`EMG_DESIGN_SYSTEM_BASELINE.md` §6); **values** are a Figma implementation
  detail.

A logo or marketing identity, if ever required, is a separate decision outside
the design-system baseline and outside MVP.

## 6. Light and dark requirements

Both themes are **mandatory and equal**. Neither is a degraded variant of the
other.

- Every semantic token is defined in both themes at creation; a mode-incomplete
  token cannot ship (`EMG_DESIGN_SYSTEM_BASELINE.md` §3).
- In Dark mode, elevation is expressed by **surface lightness, not shadow**.
- The classification range must remain visually distinct and mutually
  distinguishable **in both themes** — verified per theme, not inferred from one.
- WCAG 2.2 AA contrast is met independently in each theme.
- Theme is a **variable mode**, never a duplicated component.

## 7. Bilingual and evidence-export considerations

- **Bilingual.** The identity is script-neutral: it privileges neither Latin nor
  Arabic. Because distinctiveness is carried by typography, the dual-script
  pairing must be selected together and optically matched
  (`EMG_DESIGN_SYSTEM_BASELINE.md` §4) — the identity is only as strong as its
  Arabic face.
- **Evidence export and print.** Evidence is printed, exported, and submitted to
  oversight bodies. Institutional Neutral was selected partly because it survives
  monochrome reproduction. Every classification, confidence, and audit state
  must remain distinguishable **in greyscale and in print**, which is why no
  state may be conveyed by colour alone.
- **Longevity.** A restrained identity ages slowly. This is a system of record;
  visual churn would itself undermine the trust claim.

## 8. Consequences

**Positive.** Maximum classification headroom. Lowest accessibility risk.
Survives print, export, and greyscale. Script-neutral. Ages well. No branding
work blocks the MVP.

**Negative — accepted.** Least distinctive of the three options; the product will
not be recognizable by colour alone. Places real weight on typography selection,
which becomes a higher-stakes decision than it would otherwise be.

**Neutral.** No product scope, architecture decision, or MVP boundary is changed.

## 9. Acceptance criteria

- **AC-1.** Institutional Neutral is recorded as Accepted with rejected
  alternatives and their trade-offs.
- **AC-2.** No logo, wordmark, marketing identity, or illustration system is
  introduced.
- **AC-3.** No final colour hex values are fixed by this record.
- **AC-4.** The classification-headroom rationale is recorded as the deciding
  factor.
- **AC-5.** Light and Dark are equal and mandatory; classification remains
  distinguishable in both.
- **AC-6.** Every state remains distinguishable in greyscale and in print.
- **AC-7.** The identity privileges neither script.
