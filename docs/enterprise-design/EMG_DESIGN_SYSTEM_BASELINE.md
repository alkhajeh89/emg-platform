# EMG Enterprise Design System Baseline

**Status:** Accepted
**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Design System Governance Authority
**Decision Date:** 2026-08-03
**Type:** L4 design authority, derived from ADR-014
**Baseline:** `develop` at `866d0f7`

**Governing authorities.** `docs/product/EMG_PRODUCT_ARCHITECTURE_FREEZE.md`
(product scope, §4 personas, §24 MVP) · **ADR-014** Enterprise Presentation
Architecture · **ADR-018** Bilingual Enterprise Architecture · **ADR-025**
tenant and operation authorization · **ADR-026 Revision 2** classification
enforcement · **ADR-034** security state and service trust · **ADR-035** human
Principal authentication · **ADR-036** application and BFF boundary · **ADR-037**
Decision domain model · **PD-001** MVP Freeze Control · **GR-001** documentation
governance.

> **Canonical authority.** This document is the **single canonical source** for
> EMG design-system decisions. It closes the gap left by ADR-014, which was
> Accepted citing an "approved Enterprise UX Architecture & Design System" that
> existed in this repository only as a stub. `docs/frontend/design-system/` is
> **derived implementation guidance** and is subordinate to this document; where
> the two differ, this document prevails.

> **Scope.** Design-system architecture and UX governance only. This document
> implements no frontend code, creates no Figma asset, and expands no product
> scope. **No Figma library exists yet** — `EMG_FIGMA_LIBRARY_STRUCTURE.md`
> describes what is to be built, not what has been built.

---

## 1. Design principles — ACCEPTED FOUNDATION

Carried from `UX_OVERVIEW.md` and the Product Vision, restated as testable rules.

1. **Evidence first.** Every assertion the UI displays is one interaction from
   its evidence. A displayed fact with no reachable evidence is a defect.
2. **Human authority over AI.** The interface never presents machine output as
   equivalent to governed record.
3. **Provenance is visible, not buried.** Source, custody, and confidence are
   surface-level attributes.
4. **Temporal accuracy.** Every view states which revision it reflects. "Now"
   is a choice, not an assumption.
5. **Zero-trust rendering.** The UI renders what the API returned. It infers
   nothing, filters nothing, and decides nothing about access.
6. **Enterprise information density.** Analysts and auditors work in dense,
   scannable layouts. Consumer whitespace is a usability cost here.
7. **Bilingual parity (ADR-018).** Arabic is not a translation layer over an
   English product. Both directions are first-class.
8. **Legibility of denial.** Denied, empty, degraded, and not-found states are
   designed as carefully as success states — they carry the platform's security
   guarantees.

## 2. Visual identity direction — Institutional Neutral (Accepted)

**Decision.** EMG adopts **Institutional Neutral**: a restrained, archival,
evidence-first visual character. Near-neutral surfaces with a single deep accent.

**Distinctiveness comes from typography and information density, not chrome.**

**Rationale.** Institutional Neutral preserves the **maximum visual headroom for
classification levels**, which is this product's hardest visual constraint; it
suits evidence export and print; and it carries the lowest accessibility risk.
Full rationale and rejected alternatives: `EMG_VISUAL_IDENTITY_DECISION.md`.

**Not decided here and not to be invented:** no logo, no marketing brand system,
no illustration style, no marketing identity. Final palette **values** are a
Figma implementation detail; this document fixes token **roles** only.

## 3. Token architecture — ACCEPTED

Three tiers. Components consume **Tier 2 only**.

| Tier | Purpose | Example | Consumed by components? |
| :--- | :--- | :--- | :--- |
| **1 — Primitive** | Raw values | `color.slate.700`, `space.4`, `radius.md` | **No** |
| **2 — Semantic** | Design intent | `color.surface.raised`, `color.classification.secret` | **Yes — exclusively** |
| **3 — Component** | Alias only | `button.primary.background` → semantic | Optional |

**Rules.**

- A component referencing a Tier 1 primitive is a review failure.
- Tier 3 introduces **no new values**; it aliases Tier 2.
- Theme (Light/Dark), density (Comfortable/Compact), and direction (LTR/RTL)
  remap Tier 2 → Tier 1. **Tier 2 names never change between modes.**
- Every semantic token is defined in **both** themes at creation. A
  mode-incomplete token cannot ship.
- Tokens are the single shared source of truth for design and code. Neither
  redefines a value independently.

**Naming.** `<category>.<role>.<variant>.<state>` —
e.g. `color.action.primary.hover`, `color.classification.confidential.background`.

## 4. Typography and bilingual hierarchy — ACCEPTED (ADR-018 binding)

**Dual-script pairing.** One Latin family and one Arabic family selected
together and optically matched: x-height and Arabic baseline height aligned at
every step. Arabic typically requires ~10–15% larger optical size for equivalent
legibility, so the scale carries a **per-script size multiplier** rather than a
single shared value.

**Scale (7 steps, density-aware):** Display · H1 · H2 · H3 · Body-L · Body ·
Caption. Line-height is looser for Arabic to accommodate diacritics and
ascenders.

**Binding rules.**

- **Never** substitute a Latin face for Arabic glyphs or vice versa — mixed
  runs break diacritic positioning.
- **Numerals:** Western Arabic (0–9) in both locales for identifier and evidence
  fidelity. Eastern Arabic numerals (٠–٩) are permitted in Arabic narrative text
  only, never in identifiers, hashes, revision numbers, or timestamps.
- **Mixed Arabic/Latin identifiers** render **LTR-isolated** inside RTL text
  using Unicode isolation applied through markup. `SafeLabel`/`SafeText` already
  reject bidi override and control characters
  (`emg-memory-graph/labels.py:22-40`); **the UI must not undo that protection**
  and must never inject bidi control characters into content.
- **Evidence content is never translated, paraphrased, or machine-rendered.** It
  displays in its source language, language-tagged, with correct direction for
  that block regardless of UI locale.
- **Security, denial, and degraded messages are authored in both languages.** An
  untranslated security control is a security defect, not a localization gap.

## 5. Calendar and date display — ACCEPTED

**Gregorian is the authoritative and default calendar.**

| Context | Rule |
| :--- | :--- |
| Evidence, audit records, revisions, APIs, identifiers, exported records | **Gregorian ISO-8601 timestamps, always.** No exception |
| English UI | Gregorian, locale-formatted |
| Arabic UI | Gregorian primary; **optional secondary Hijri date** may be displayed alongside |
| Hijri conversion | **Presentational only.** It never changes stored meaning, never round-trips into storage, and is never the basis of a comparison, sort, filter, or export |

Timestamps always carry an explicit timezone. Hijri is a display convenience for
Arabic readers, never a data representation.

## 6. Semantic colour roles — ACCEPTED (roles only; values are Figma detail)

All families defined in **both** Light and Dark.

| Family | Roles |
| :--- | :--- |
| Background | `canvas`, `sunken`, `overlay` |
| Surface | `default`, `raised`, `overlay`, `selected` |
| Border | `subtle`, `default`, `strong`, `focus` |
| Text | `primary`, `secondary`, `tertiary`, `inverse`, `link`, `disabled` |
| Action | `primary`, `secondary`, `ghost`, `destructive` × `default`/`hover`/`active`/`disabled` |
| Focus | `ring` — single, high-contrast, never removed |
| Status | `success`, `warning`, `error`, `information` — each with `background`/`border`/`text`/`icon` |
| Disabled | `background`, `text`, `border` |

### 6.1 Exclusive classification colour range — BINDING

`color.classification.unclassified` · `.internal` · `.confidential` · `.secret`

**This range is exclusive.** No status, chart, decorative, action, or brand
token may draw from it. No classification token may be reused for any
non-classification purpose. This exclusivity is the reason Institutional Neutral
was selected (§2).

### 6.2 Evidence confidence

`color.confidence.high` · `.medium` · `.low` · `.unknown` — each **must** be
distinguishable without colour (icon, label, or pattern).

### 6.3 Audit and integrity status

`color.audit.verified` · `.unverified` · `.broken` · `.pending`. `broken` maps
to the strongest available alarm treatment and always carries an explicit text
label — a broken integrity chain must never be conveyed by colour alone.

### 6.4 Colour rules

Every state carries a **non-colour** signal. Chart and graph palettes are
colourblind-safe **and** distinguishable in greyscale, because evidence is
printed and exported.

## 7. Spacing, grid, breakpoints, radii, elevation, density — ACCEPTED

- **Spacing:** 4px base — `0, 1(4), 2(8), 3(12), 4(16), 5(20), 6(24), 8(32),
  10(40), 12(48), 16(64)`. No arbitrary values.
- **Grid:** 12-column fluid, desktop-first, max content width, with full-bleed
  exceptions for graph and timeline canvases.
- **Breakpoints:** `sm 640` · `md 768` · `lg 1024` · `xl 1280` · `2xl 1536`.
  Enterprise default targets `xl`.
- **Radii:** `none` · `sm 2` · `md 4` · `lg 8` · `full`. Restrained: this is a
  record system.
- **Elevation:** 5 levels — `flat`, `raised`, `overlay`, `modal`, `popover`. In
  Dark mode elevation is expressed by **surface lightness**, not shadow.
- **Density:** `comfortable` (default) and `compact` (analyst/table-heavy).
  Density remaps spacing and type steps **only** — never colour, never
  semantics, never classification treatment.

## 8. Component hierarchy and admission criteria — ACCEPTED

**Three tiers.** **Primitive** (button, input, badge) → **Composite** (data
table, drawer, card) → **Domain** (Evidence Card, Classification Badge, Timeline
Track, Graph Canvas). Domain components may compose Composites; **the reverse is
forbidden**.

**Admission criteria — all mandatory.** A component enters the library only with:

1. Both themes (Light, Dark)
2. Both directions (LTR, RTL)
3. Both densities (Comfortable, Compact)
4. Full keyboard support and visible focus
5. Screen-reader semantics and accessible name
6. All state variants: `default`, `hover`, `focus`, `active`, `disabled`,
   `loading`, `empty`, `error`, **`denied`**
7. Semantic tokens only — no primitive references, no hardcoded values

**A component without a `denied` state is not shippable in EMG.**

## 9. Classification-safe rendering — BINDING (ADR-026 Revision 2)

**The UI applies no clearance logic whatsoever.** It renders exactly what the
API returned. This is the security model, not a simplification.

| Server behaviour (ADR-026) | UI rendering rule |
| :--- | :--- |
| Denied entity → not-found | Render **identically** to a genuinely non-existent entity. No distinct copy, icon, colour, or error code |
| Denied list item → silently pruned | Render the list as returned. **No "N hidden", no gap, no placeholder row, no adjusted total** |
| Denied path → `found=false` | Render "no path found" identically to genuine absence |
| Denied history fact → empty item | Render as no data |

**Prohibitions.**

- No "N hidden" leakage in **any** form — counts, totals, pagination arithmetic,
  scroll height, or response timing.
- No UI-side inference of classification.
- **No colour-only classification signal.** Every classification badge carries a
  **text label in both languages** plus a shape or icon.
- Classification badges are always visible on classified objects — never
  hover-only, never truncated away.
- Absence of a badge means `UNCLASSIFIED`, rendered explicitly. Classification is
  never inferred from absence.

**Security Context Banner.** A persistent shell element showing tenant and the
caller's effective clearance, so a user always knows the lens they are viewing
through.

## 10. Accessibility — ACCEPTED: WCAG 2.2 Level AA

Resolves the `TBD` in `docs/frontend/design-system/ACCESSIBILITY_GUIDELINES.md`.
AAA where inexpensive: focus visibility and evidence-view text contrast.

- **Keyboard.** Every interaction reachable. Visible focus always — `outline:
  none` without an equivalent indicator is a defect. Logical order in both
  directions. Skip links. `Escape` closes overlays. Focus trapped in modals and
  restored on close.
- **Screen readers.** Landmark regions; `aria-live` for async results and
  errors; **classification announced as text**; `lang` switches per content block
  for correct pronunciation.
- **Contrast.** 4.5:1 body text; 3:1 large text and UI boundaries; 3:1 for graph
  edges and timeline marks against their background.
- **Reduced motion.** `prefers-reduced-motion` removes all non-essential
  animation; timeline replay becomes stepped rather than animated.
- **Zoom and reflow.** Usable at 400% without horizontal scrolling, except graph
  and table canvases, which provide explicit pan affordances.
- **Graph accessibility — hard requirement.** The node-link canvas is **never**
  the only access path. Every graph view has an equivalent keyboard-navigable
  list or tree exposing the same data.
- **Timeline accessibility.** An ordered, keyboard-navigable list equivalent with
  revision numbers and timestamps as text.
- **Colour independence.** Every state distinguishable in greyscale.

## 11. RTL / LTR — ACCEPTED (ADR-018 binding)

**Full layout mirroring**, not text-only. Implemented with logical properties
(`inline-start`/`inline-end`), never physical left/right.

- Navigation, drawers, tables, breadcrumbs, progress, and pagination mirror.
- **Directional icons mirror** (back/forward, next/previous, indent, tree
  expanders). **Non-directional icons never mirror** (clock, search, warning,
  checkmark, external-link).
- **Charts and timelines mirror axis direction** — in RTL, time flows
  right-to-left.
- **Graph canvases do not auto-mirror node positions** (spatial memory), but
  their controls and panels do.
- Mixed content, evidence, and security messaging follow §4.
- Direction is a **variable mode**, never a duplicated component (§ Figma
  structure).

## 12. Motion — ACCEPTED

- **Purposeful only.** Motion communicates state change, spatial relationship, or
  progress. No decorative animation.
- **Duration:** 100ms micro · 200ms standard · 300ms overlay. Nothing exceeds
  400ms.
- **Easing:** ease-out for entry, ease-in for exit, linear for progress only.
- **Reduced motion honoured absolutely**, including timeline replay.
- **Real-time:** **MVP is request/response only.** No websockets, no polling, no
  live push — no event-push backend exists. Refresh is explicit and
  user-initiated, with a visible "as of" timestamp, reinforcing principle 4.

## 13. Responsive posture and mobile — ACCEPTED

**Desktop-first.** Tablet is a supported reading and review posture.

**Mobile is read-only by design.** No mutation, no approval, no reclassification,
and no evidence export from mobile in MVP.

- Graph degrades to the list/adjacency equivalent below `lg`.
- Timeline degrades to a vertical ordered list.
- Side navigation collapses to an overlay drawer.
- Dense tables become stacked cards with the same fields and the same
  classification treatment.

## 14. MVP component inventory — ACCEPTED

Scope is the four frozen Freeze §24 surfaces plus session and state handling.

| Surface | Components |
| :--- | :--- |
| **Sign-in / session** | Sign-in redirect state · session-expired dialog · unauthorized (403) · authentication-error · sign-out confirmation · Security Context Banner |
| **Knowledge Graph Explorer** | App shell · side nav · graph canvas · graph controls (zoom, pan, depth, direction) · **keyboard-navigable list equivalent** · entity summary card · neighbour list · path result · filters · pagination · drawer · classification badge |
| **Decision Timeline** | Timeline track · revision marker · revision detail panel · compare view · **ordered list equivalent** · date/time display · pagination |
| **Evidence & Source Viewer** | Evidence card · citation block · custody chain list · integrity/audit status indicator · source metadata · bilingual content block · export control |
| **Keyword Search with grounded "why"** | Search input · result list · result card · grounded-answer block with citations · empty-result state |
| **States** | Loading (skeleton + spinner) · empty · error · **denied** · **degraded** · not-found · offline |
| **Cross-cutting primitives** | Button · input · select · checkbox · radio · table · tabs · tooltip · dialog · drawer · toast · breadcrumb · link · badge · icon |

### 14.1 Explicit exclusions — BINDING (PD-001)

**Excluded from MVP design and from this inventory:**

- **Executive Dashboard** — outside MVP per Freeze §24 and PD-001. No KPI, chart,
  coverage score, or risk indicator component may be designed for MVP.
- **AI Assistant / Copilot** — outside MVP. The MVP grounded "why" is a search
  result presentation, **not** an assistant surface.
- Workflows and approvals UI · administration console · integrations console ·
  notification centre · mobile mutation flows.

PD-001 §5 additionally **prohibits placeholder executive metrics** in MVP in any
form, including behind feature flags or in demo environments.

## 15. Acceptance criteria

- **AC-1.** This document is the canonical design-system authority;
  `docs/frontend/design-system/` is derived and subordinate.
- **AC-2.** Components consume Tier 2 semantic tokens only; no primitive
  reference and no hardcoded value survives review.
- **AC-3.** Every semantic token is defined in both Light and Dark at creation.
- **AC-4.** The classification colour range is exclusive; no other family draws
  from it.
- **AC-5.** No state — classification, confidence, audit, or status — is conveyed
  by colour alone.
- **AC-6.** No UI surface exposes a "N hidden" signal in any form.
- **AC-7.** The UI applies no clearance logic; denied and non-existent render
  identically.
- **AC-8.** Every component in the library carries a `denied` state.
- **AC-9.** WCAG 2.2 AA is met, including 400% reflow and reduced motion.
- **AC-10.** Graph and timeline each have a keyboard-navigable equivalent
  exposing the same data.
- **AC-11.** Full RTL mirroring via logical properties; direction is a mode, not
  a duplicated component.
- **AC-12.** Evidence is never translated; security messages exist in both
  languages.
- **AC-13.** All stored and exported timestamps are Gregorian ISO-8601; Hijri is
  presentational only.
- **AC-14.** Identifiers, hashes, revision numbers, and timestamps use Western
  numerals in both locales.
- **AC-15.** MVP contains no Dashboard, no AI Assistant, and no placeholder
  executive metric.
- **AC-16.** Mobile exposes no mutation, approval, reclassification, or export.
- **AC-17.** No logo, marketing identity, or illustration system is introduced.
