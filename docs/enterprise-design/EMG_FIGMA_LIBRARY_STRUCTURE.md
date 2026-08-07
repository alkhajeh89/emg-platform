# EMG Figma Library Structure

**Status:** Accepted
**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Design System Governance Authority
**Decision Date:** 2026-08-03
**Type:** Figma implementation detail, derived from `EMG_DESIGN_SYSTEM_BASELINE.md`
**Baseline:** `develop` at `866d0f7`

> **No Figma asset exists.** This document specifies the structure to be built.
> It does not describe, claim, or imply any existing Figma file, library,
> variable collection, or component. Nothing here is a design decision — every
> decision it implements is recorded in `EMG_DESIGN_SYSTEM_BASELINE.md` and
> `EMG_VISUAL_IDENTITY_DECISION.md`. Where this document and the baseline
> differ, **the baseline prevails**.

---

## 1. Three files, published in dependency order

| # | File | Contains | Consumes |
| :--- | :--- | :--- | :--- |
| 1 | **EMG Foundations** | Variable collections only | — |
| 2 | **EMG Components** | The component library | Foundations |
| 3 | **EMG Product** | Screen compositions and prototypes | Components (and, transitively, Foundations) |

**Publication order is strict: Foundations → Components → Product.** A file is
never published before the library it consumes. A breaking change in Foundations
is published, then absorbed in Components, then in Product — never in reverse.

---

## 2. EMG Foundations

**Contains variable collections only. No components, no frames, no screens.**

### 2.1 Variable collections and modes

| Collection | Modes | Purpose |
| :--- | :--- | :--- |
| `Primitive` | *(none)* | Raw values — the Tier 1 palette, spacing, radii, type sizes. **Never referenced by a component** |
| `Semantic` | **Light**, **Dark** | Tier 2 design intent — the only collection components bind to |
| `Density` | **Comfortable**, **Compact** | Remaps spacing and type steps only |
| `Direction` | **LTR**, **RTL** | Drives logical spacing, mirroring, and icon direction |

**Direction and theme are modes, never variants.** A component is authored once
and resolves per mode. Duplicating a component to support Dark or RTL is
prohibited (§6).

### 2.2 Semantic-token mapping

Every Tier 2 variable resolves to a Tier 1 primitive per mode. The Tier 2 **name
never changes** between modes.

```
Semantic                          Light mode        Dark mode
color.surface.default        →    primitive.n-0     primitive.n-900
color.surface.raised         →    primitive.n-50    primitive.n-800
color.text.primary           →    primitive.n-900   primitive.n-50
color.border.default         →    primitive.n-200   primitive.n-700
color.action.primary.default →    primitive.a-600   primitive.a-400
color.focus.ring             →    primitive.a-500   primitive.a-300
color.classification.secret  →    primitive.c-sec-L primitive.c-sec-D
color.confidence.low         →    primitive.f-low-L primitive.f-low-D
color.audit.broken           →    primitive.u-brk-L primitive.u-brk-D
```

Primitive names above are placeholders for structure. **Final values are set
when the Foundations file is built** — `EMG_VISUAL_IDENTITY_DECISION.md` fixes
the Institutional Neutral direction and deliberately fixes no hex values.

### 2.3 Mandatory completeness

- Every `Semantic` variable is defined in **both** Light and Dark at creation. A
  mode-incomplete variable cannot be published.
- The `color.classification.*` family is an **exclusive range**; no other
  semantic variable may resolve to a classification primitive
  (baseline §6.1).
- Contrast is verified **per theme**, not inferred from one.

### 2.4 Pages

`📖 Cover` · `🎨 Primitives (documentation)` · `🔗 Semantic Mapping (documentation)` ·
`📏 Scales (documentation)`

---

## 3. EMG Components

Consumes Foundations. **Binds to `Semantic` only** — a component bound to a
`Primitive` variable fails review.

### 3.1 Pages

| Page | Contents |
| :--- | :--- |
| `📖 Cover` | Version, changelog, publication status, consuming files |
| `🔤 Primitives` | Button, input, select, checkbox, radio, link, badge, icon, tooltip |
| `🧩 Composites` | Data table, drawer, dialog, card, tabs, breadcrumb, pagination, filters, toast |
| `🏛 Domain` | Classification Badge, Evidence Card, Citation Block, Custody Chain, Audit Status, Entity Summary, Timeline Track, Revision Marker, Graph Canvas, Graph Controls, Security Context Banner, Bilingual Content Block |
| `🚦 States` | Loading, empty, error, **denied**, **degraded**, not-found, offline |
| `📐 Patterns` | App shell, navigation, search, form layout, list-equivalent patterns for graph and timeline |
| `📄 Documentation` | Usage, admission criteria, do/don't, accessibility notes per family |
| `🗄 Archive` | Deprecated components (§8) |

### 3.2 Naming convention

```
Category/Component/Variant
```

- `Primitives/Button/Primary`
- `Composites/DataTable/Default`
- `Domain/ClassificationBadge/Secret`
- `States/Denied/Entity`

Categories are exactly: `Primitives`, `Composites`, `Domain`, `States`,
`Patterns`. PascalCase for component names; no spaces; no theme, density, or
direction in the name.

### 3.3 Component variants

Every component carries:

| Property | Values |
| :--- | :--- |
| `State` | `default`, `hover`, `focus`, `active`, `disabled`, `loading`, `empty`, `error`, **`denied`** |
| `Size` | `sm`, `md`, `lg` *(where meaningful)* |

Domain components add, where relevant:

| Property | Values |
| :--- | :--- |
| `Classification` | `unclassified`, `internal`, `confidential`, `secret` |
| `Confidence` | `high`, `medium`, `low`, `unknown` |
| `AuditStatus` | `verified`, `unverified`, `broken`, `pending` |

**A component without a `denied` state is not admissible** (baseline §8).

### 3.4 Direction and theme handling

- **Theme (Light/Dark):** `Semantic` collection mode. Not a variant. Not a
  duplicate.
- **Direction (LTR/RTL):** `Direction` collection mode driving logical spacing
  and mirroring. Not a variant. Not a duplicate.
- **Density (Comfortable/Compact):** `Density` collection mode. Not a variant.
- **Directional icons** are authored as a mirroring-enabled set; non-directional
  icons (clock, search, warning, checkmark, external-link) are explicitly
  excluded from mirroring (baseline §11).

---

## 4. EMG Product

Consumes Components. Contains **no** component definitions — compositions only.

### 4.1 Pages

`📖 Cover` · `🔐 Session` (sign-in redirect, session expired, unauthorized,
authentication error, sign-out) · `🕸 Knowledge Graph Explorer` ·
`🕐 Decision Timeline` · `📎 Evidence & Source Viewer` ·
`🔎 Keyword Search with grounded "why"` · `🚦 States` (surface-specific denied,
empty, loading, degraded, not-found) · `▶️ Prototypes` · `🗄 Archive`

### 4.2 Scope boundary — BINDING

Product pages cover **exactly** the four frozen Freeze §24 MVP surfaces plus
session and state handling.

**No page may be created for:** Executive Dashboard · AI Assistant / Copilot ·
workflows and approvals · administration · integrations · notification centre ·
mobile mutation flows.

Per **PD-001 §5**, no frame may contain a placeholder executive metric — no KPI,
coverage score, risk count, or chart — including in prototypes or demo frames.

### 4.3 Prototype pages

Prototypes cover the primary MVP journeys only: analyst lineage traversal
(search → entity → explorer → timeline → evidence), auditor evidence-and-custody
review, and the session lifecycle including expiry and denial. Prototypes are
illustrative and carry no authority.

---

## 5. Documentation pages

Each library carries a `📄 Documentation` page recording: purpose, admission
criteria, usage and anti-patterns, accessibility notes (keyboard, screen-reader,
contrast), RTL notes, and the governing baseline section. Documentation
describes; it never decides. Decisions live in
`EMG_DESIGN_SYSTEM_BASELINE.md`.

---

## 6. Prohibited duplication — BINDING

**Components must not be duplicated to support theme, direction, or density.**

| Prohibited | Correct approach |
| :--- | :--- |
| `Button/Primary/Dark` | `Semantic` mode = Dark |
| `Button/Primary/RTL` | `Direction` mode = RTL |
| `DataTable/Compact` as a separate component | `Density` mode = Compact |

Duplication multiplies the library by eight (2 themes × 2 directions × 2
densities) and guarantees drift. Any such duplicate fails review.

---

## 7. Publication and versioning

- Publish in order: Foundations → Components → Product.
- Every publication carries a changelog entry on the file's `📖 Cover`.
- A breaking change (renamed or removed semantic variable, removed variant,
  changed default) is announced before publication and absorbed downstream in
  order.
- Consuming files are never left pointing at an unpublished library state.

---

## 8. Archive and deprecation process

- Deprecated components move to `🗄 Archive` within their file. **Nothing is
  deleted.**
- An archived component records: deprecation date, reason, and replacement.
- Archived components are removed from the published library surface but remain
  inspectable, so historical Product frames remain interpretable.
- A component may only be archived once every consuming Product frame has been
  migrated.

---

## 9. Acceptance criteria

- **AC-1.** Three files exist with the stated contents and dependency order.
- **AC-2.** Foundations contains variable collections only — no components.
- **AC-3.** `Semantic` carries Light and Dark modes; `Density` carries
  Comfortable and Compact; `Direction` carries LTR and RTL.
- **AC-4.** Every `Semantic` variable is defined in both themes.
- **AC-5.** No component binds to a `Primitive` variable.
- **AC-6.** No component is duplicated for theme, direction, or density.
- **AC-7.** Every component carries a `denied` state.
- **AC-8.** Naming follows `Category/Component/Variant` with no theme, density,
  or direction in the name.
- **AC-9.** The classification range is exclusive; no other semantic variable
  resolves to a classification primitive.
- **AC-10.** Product pages cover only the four MVP surfaces plus session and
  states; no Dashboard or AI Assistant page exists.
- **AC-11.** No frame contains a placeholder executive metric.
- **AC-12.** Deprecated components are archived with date, reason, and
  replacement — never deleted.
- **AC-13.** Publication follows Foundations → Components → Product.
