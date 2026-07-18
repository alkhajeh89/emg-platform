# Sprint 14 — Review-Fix Implementation Report

**Scope:** Implement **only** the two approved architecture-review fixes for the
Universal Connector Framework (EPIC-13 / FEAT-13-1, `libs/python/emg-connectors`).
Sprint 14 was **not** restarted; only the minimum necessary files were touched.
**Nothing committed, pushed, or merged.**

**Branch:** `feature/sprint-14-universal-connector-framework`
**Repository:** `/Users/mak/Documents/GitHub/emg-platform`

---

## 0. Repository verification (before any change)

| Check | Result |
| --- | --- |
| Current branch = `feature/sprint-14-universal-connector-framework` | ✅ |
| Sprint 14 work present and uncommitted (`libs/python/emg-connectors/`, Sprint 14 docs) | ✅ |
| Working tree still uncommitted at finish (nothing staged/committed) | ✅ |
| Frozen Backlog `EMG_Engineering_Backlog_v1.0.md` untouched | ✅ |

The uncommitted Sprint 14 tree was inspected first; the fixes were applied as
in-place edits to existing Sprint 14 modules, tests, and docs — **no new source
files, no restart**.

---

## 1. Fix 1 — Extensible capability model (keep standard, add vendor extensions)

**Problem (review):** the capability model was closed — a future connector could
not advertise a capability the core did not enumerate without editing the
framework.

**Change:** standard capabilities remain the closed, strongly-typed
`ConnectorCapability` enum (unchanged). Connectors may additionally declare
**vendor-specific `extension_capabilities`** — free-form strings, conventionally
namespaced (e.g. `"acme:delta_feed"`) — with no framework change and strong
validation preserved:

- `limits.py` — added `MAX_EXTENSION_CAPABILITIES = 256`.
- `capabilities.py`
  - `ConnectorCapabilities.extension_capabilities: tuple[SafeLabel, ...] = ()`
    (safe-label validated → control/bidi/NUL rejected; sorted-unique normalised;
    bounded; **cannot reuse a standard capability value**).
  - `ConnectorCapabilities.supports_extension(capability: str) -> bool`.
  - `CapabilityRequirement.required_extension_capabilities`.
  - `CapabilityNegotiation.missing_extension_capabilities`.
  - `negotiate()` resolves standard and extension capabilities symmetrically and
    deterministically (missing extension set sorted; factored into `satisfied`).
- `metadata.py` — `ConnectorDescriptor.supports_extension(...)` convenience.

**Outcome:** the extension point is open (no core change to add a capability) while
typing stays strong (standard capabilities remain an enum) and the two namespaces
cannot collide.

---

## 2. Fix 2 — Single source of truth (eliminate the loader/registry split)

**Problem (review):** plugin registration (`ConnectorPluginLoader`) and connector
registration (`ConnectorRegistry`) were two independently-populated stores that
could drift.

**Change:** `ConnectorPluginLoader` now **owns one internal `ConnectorRegistry`**
and is the single source of truth:

- `plugin.py`
  - `__init__` creates a private `self._registry = ConnectorRegistry()`.
  - `register()` — after compatibility + validation, performs an **atomic**
    pre-check for cross-plugin `connector_id` collisions, then commits the plugin
    and auto-publishes every provided connector into the registry (all-or-nothing:
    a colliding plugin leaves **no** partial state).
  - `unregister()` — withdraws exactly that plugin's connectors, then removes the
    plugin (no drift).
  - Read API added: `connector_ids()`, `connector_descriptors()`,
    `get_connector(id)`, `plugin_id_for_connector(id)`, and `discovery()` (returns
    a `ConnectorDiscovery` over the one registry).
- Import direction verified: `plugin → {registry, discovery}`; neither imports
  `plugin`. **No import cycle.**

The standalone `ConnectorRegistry` / `ConnectorDiscovery` remain available as
lower-level primitives, but the normal register → discover → create flow no longer
needs a separate registry step.

---

## 3. Tests added (+10; package 105 → 115)

**`test_capabilities.py` (extension capabilities):**
`test_extension_capabilities_supported_alongside_standard`,
`test_extension_capabilities_normalised_sorted_unique`,
`test_extension_capability_may_not_reuse_standard_value`,
`test_extension_capability_rejects_control_bidi`,
`test_negotiate_extension_capabilities`,
`test_extension_negotiation_is_deterministic`.

**`test_plugin.py` (loader single source of truth):**
`test_registering_a_plugin_auto_publishes_its_connectors` (automatic registry
population), `test_unregistering_a_plugin_withdraws_its_connectors` (plugin-removal
consistency), `test_cross_plugin_connector_id_collision_is_atomic` (no partial
state), `test_two_loaders_do_not_share_connector_state` (isolation).

These cover the three required categories: **extension capabilities**, **automatic
registry population**, **plugin-removal consistency**.

---

## 4. Documentation updated

`docs/engineering/connectors-extension-guide.md` (registration & discovery flow
rewritten — loader auto-publishes, no separate `ConnectorRegistry.register` step;
standard + extension capabilities section), `connectors-plugin-author-guide.md`
(register/use flow + vendor-capability note), `connectors-architecture.md`
(single-source-of-truth + extensible-capabilities subsections), package `README.md`
(capabilities, plugin architecture, usage example), `SPRINT-14-STATUS.md`
(post-review-fixes section, plugin model, extension points, counts 105→115 /
830→840), `CHANGELOG.md` (Sprint 14 section + review-fix note), `ARCHITECTURE_STATUS.md`
(refinement note), `docs/engineering/security-limitations.md` (extensible-capabilities
+ single-source-of-truth controls), `docs/engineering/testing-strategy.md` (new
test descriptions).

---

## 5. Quality gates (all green)

| Gate | Result |
| --- | --- |
| `pytest` (emg-connectors package) | **115 passed** (was 105) |
| `pytest libs services` (full regression) | **840 passed, 16 skipped** (was 830/16) |
| Golden regressions | **10 passed** (incl. connector + plugin lifecycle golden tables, audit-hash, ontology descriptor, lifecycle, trust scores) |
| `ruff check` | **All checks passed** |
| `black --check --line-length 100` | **Clean** (34 files) |
| `mypy --strict` (src + tests) | **Success — no issues found in 34 source files** |
| Dependency-direction verification | **Clean** — `emg-common-types`, `emg-errors`, `pydantic` only; no sibling imports; zero reverse deps |
| Forbidden-technology + no-vendor-branching guards | **Pass** (no network/SDK import; no vendor token in executable core) |
| Import-cycle check (incl. new `plugin → registry/discovery` edges) | **NONE** |
| Secret scan | **Clean** (only match is the `BEARER_TOKEN` auth-mechanism enum name) |
| Public API exports | **73** — unchanged (fixes added fields/methods to existing exported types) |

---

## 6. Constraints honoured

- No new epic/feature ids; frozen Backlog untouched (EPIC-06 = Search unchanged).
- No real connector; no networking/persistence/auth/HTTP/SDK/CLI/UI; no vendor
  branching in the core; no dynamic plugin loading (in-memory registration only).
- Authentication remains a declaration with an opaque `credential_ref`; no secrets.
- **Not committed, not pushed, not merged.**

**Status:** the two approved review fixes are implemented, tested, and verified.
Sprint 14 (FEAT-13-1) remains complete and awaiting review/approval.
