# Sprint 14.5 — Developer Experience & Repository Bootstrap

**Status:** Complete — pending review. Strictly limited to repository bootstrap,
local developer setup, tooling, onboarding, and CI-supporting configuration.
**No application logic** under `libs/python/*/src`, `services/*/src`, or `apps/*`
was modified (verified: `git status` shows zero changes under those paths).
Nothing committed, pushed, or merged.

**Branch:** `feature/sprint-14.5-developer-experience` (from `develop` @ `baa6242`,
which contains merged Sprint 13 + Sprint 14).

**Epic:** Filed under a **Developer Experience / Repository Readiness** track
(engineering enablement), **not** the frozen product feature backlog — no product
Epic/Feature id was created, modified, or renumbered.

---

## 1. Summary of root causes

The intended workflow (`make bootstrap` → `source .venv/bin/activate` →
`make test`/`make lint`) could not succeed on a fresh clone for these reasons:

1. **`make bootstrap` never installed anything.** The Makefile target did not
   call `tools/scripts/bootstrap.sh`; it only ran `pre-commit install` (which
   aborted — see #4) and `make up`. Libraries were never installed, so
   `make test` failed at import/collection.
2. **No isolated environment.** `bootstrap.sh` pip-installed into the ambient
   interpreter (PEP 668 "externally-managed" failures; pollution). The one
   `.venv` that did exist locally had been created with **Python 3.14.6** — the
   exact "silently unsupported interpreter" failure the sprint calls out.
3. **Sibling dependency resolution was broken.** `install-libs.sh` installed the
   proprietary `emg-*` packages one-at-a-time in alphabetical order. Because they
   depend on each other by name and are not on any index, the first package's
   sibling dependency was unresolved and pip tried (and failed) to fetch it from
   PyPI.
4. **`.pre-commit-config.yaml` did not exist**, yet the Makefile and bootstrap
   ran `pre-commit install` — a hard failure.
5. **`black` was never installed** by any script, though `run-lint.sh`/`run-fmt.sh`
   and `[tool.black]` require it.
6. **No root dev-dependency manifest** existed; there was no single place that
   installed pytest/ruff/black/mypy/pre-commit/build/pip-audit.
7. **No `.python-version`**, and bootstrap performed **no interpreter validation**.
8. **`.env.example` was missing**, though onboarding, bootstrap, and `.gitignore`
   (`!.env.example`) all referenced it.
9. **Service test dependencies were never installed** — `services/{identity,audit}`
   (and third-party deps like `cryptography`, `pytest-asyncio`) are required by
   root test discovery (`testpaths = ["libs","services"]`).
10. **Docs described behaviour that did not match the repo** and referenced
    non-existent CI files (`.github/workflows/ci.yml`, `.github/settings.yml`).
11. **Latent `find … | grep -q` guard bug** in `run-tests.sh`/`run-lint.sh`:
    under `set -o pipefail`, `grep -q` closes the pipe early, `find` dies with
    SIGPIPE (141), and the guard spuriously reports "no tests" (race-dependent).

---

## 2. Files added / modified

**Added (7):**

| File | Purpose |
| --- | --- |
| `.python-version` | Pins the supported interpreter (`3.10`). |
| `requirements-dev.txt` | Root dev toolchain (pytest, pytest-asyncio, ruff, black, mypy, types-PyYAML, pre-commit, build, pip-audit) with a documented versioning policy. |
| `.pre-commit-config.yaml` | trailing-whitespace, end-of-file-fixer, check-yaml, check-added-large-files, ruff, black — versions aligned with the toolchain. |
| `.env.example` | Non-secret local-dev placeholders for `EMG_IDENTITY_*` / `EMG_AUDIT_*` (match docker-compose + service defaults). |
| `tools/scripts/_venv.sh` | Sourced helper: repo root, `.venv` paths, supported-Python check, `emg_require_venv`. |
| `tools/scripts/install-services.sh` | Editable-installs installable `services/*` packages with dev extras. |
| `tools/scripts/setup-check.sh` | Non-destructive environment diagnostic (`make setup-check`). |

**Modified (9):**

| File | Change |
| --- | --- |
| `Makefile` | `bootstrap` now delegates to `tools/scripts/bootstrap.sh`; added `setup-check`; `pre-commit` uses `.venv/bin/pre-commit`. All other targets preserved. |
| `tools/scripts/bootstrap.sh` | Full rewrite: interpreter selection + validation (3.10–3.12), idempotent `.venv` create/repair, dev-toolchain install, editable libs+services, hooks, `.env`, soft docker step. Uses `.venv/bin/python` explicitly (no activation dependency). |
| `tools/scripts/install-libs.sh` | Single-invocation editable install of all libs so `emg-*` siblings resolve locally; idempotent; progress output; prefers `.venv`. |
| `tools/scripts/run-tests.sh` | Uses `.venv` pytest; clear error if not bootstrapped; fixed the SIGPIPE guard. |
| `tools/scripts/run-lint.sh` | Uses `.venv` ruff/black; clear error if not bootstrapped; fixed the SIGPIPE guard. |
| `tools/scripts/run-fmt.sh` | Uses `.venv` ruff/black; clear error if not bootstrapped; fixed the SIGPIPE guard. |
| `docs/engineering/onboarding.md` | Exact fresh-clone commands, activation, supported Python, re-run guidance, troubleshooting. |
| `tools/README.md` | New scripts documented; corrected claims about non-existent CI files. |
| `README.md` | Getting-Started rewritten; corrected CI-file claim in Contributing. |

No application source under `libs/python/*/src`, `services/*/src`, or `apps/*`
was touched.

---

## 3. Design decisions

- **Single-invocation editable install (no topological sort).** Passing every
  local package to one `pip install -e … -e …` lets pip resolve the proprietary
  `emg-*` siblings from the projects on the command line, so nothing is fetched
  from PyPI for them and install order is irrelevant. Simpler and more robust
  than hand-maintaining a dependency order. Libs then services (two passes) so a
  service's `emg-*` siblings are already present.
- **Supported range 3.10–3.12, pinned to 3.10.** The toolchain targets py310
  (root `pyproject.toml`) and the whole suite is validated on 3.10. Bootstrap
  prefers `python3.10/3.11/3.12` and **refuses** 3.13/3.14 with an actionable
  message (pyenv / `EMG_PYTHON` override) rather than silently using a newer
  default. An existing `.venv` on an unsupported/broken interpreter is recreated.
- **Dev toolchain as `requirements-dev.txt` (floors, not pins).** Floors match
  the packages' own `dev` extras so the root toolchain can't resolve below what a
  package expects; **Black is capped to `<25.0`** because its stable style is
  version-sensitive, keeping `requirements-dev.txt` == `.pre-commit-config.yaml`
  (24.10.0) == how the tree is formatted.
- **Scripts prefer `.venv/bin/*` and fail loudly otherwise.** `run-tests`/
  `run-lint`/`run-fmt` never rely on globally-installed tools; if `.venv` is
  missing they print "run `make bootstrap`".
- **Docker is soft.** Bootstrap completes (and `make test`/`make lint` work)
  without Docker; infra is skipped with a warning (`EMG_SKIP_DOCKER=1` to force-skip).
- **`.env` is generated, `.env.example` is tracked**, containing only non-secret
  local-dev placeholders that match docker-compose and the pydantic-settings
  defaults.

---

## 4. Verification results

Run on Python 3.10.12 (Docker absent in this environment → infra soft-skipped).

| Check | Result |
| --- | --- |
| `bash -n` on all 8 shell scripts (shellcheck unavailable in sandbox — see Risks) | **All pass** |
| `make bootstrap` (fresh: recreated the broken 3.14 `.venv` → 3.10) | **Success** — venv + toolchain + 14 libs + 2 services + hooks + `.env` |
| `make bootstrap` (re-run) | **Idempotent** — ".venv already present and supported — reusing" |
| `source .venv/bin/activate` | Works (`VIRTUAL_ENV` set; `.venv/bin` on PATH) |
| `.venv/bin/python --version` | **Python 3.10.12** (supported; not the 3.14 default) |
| `python -m pip check` | **No broken requirements found** |
| `make setup-check` | **All required checks OK** (docker WARN only) |
| `make test` | **840 passed, 16 skipped** (unchanged from Sprint 13/14 baseline; now includes `services/{identity,audit}` suites) |
| `make lint` — ruff | **All checks passed!** |
| `make lint` — black | **6 pre-existing files** flagged (see Risks) → target exits 1 |
| `make pre-commit` | config **valid**; hooks provision & run — `check-yaml` **Passed**, `ruff` **Passed**; black hook mirrors the same 6 pre-existing files |
| Key imports after bootstrap | `emg_identity`, `emg_audit_service`, `emg_connectors`, `cryptography` all **importable** |
| Application source modified | **None** (`git status`: 0 files under `*/src`, `apps/`) |

Installed toolchain: ruff 0.15.22, black 24.10.0, mypy 2.3.0, pytest 9.1.1,
pre-commit 4.6.0, build 1.5.0, pip-audit 2.10.1.

---

## 5. Remaining risks

1. **Pre-existing formatting debt blocks `make lint` (the one non-green item).**
   Black (24.10.0) reports 6 files needing whitespace-only reformatting —
   `services/identity/src/{config,main,audit,service_token_validator}.py`,
   `services/identity/tests/test_service_auth_router.py`, and
   `libs/python/emg-policy-engine/tests/test_loader.py`. These are **pre-existing**
   (surfaced only now that Black is installed) and sit in application code, so per
   this sprint's scope they were **not** modified. Fix is a one-liner —
   `make fmt` — but it touches identity + policy-engine source and should land as
   a separate change under those CODEOWNERS. Until then `make lint` exits non-zero.
2. **shellcheck not run.** It could not be installed in the sandbox (no network
   for the binary); scripts were syntax-checked with `bash -n` only. Recommend
   running `shellcheck tools/scripts/*.sh` in an environment where it's available.
3. **Docker not exercised here.** The compose step is soft-skipped; the
   `docker compose up` path was not executed in this environment.
4. **Editable installs re-fetch build backends under isolation**, which is slow on
   constrained networks (observed here). Functionally correct; a future
   optimization could add a shared `--no-build-isolation` fast path.
5. **Empty scaffold dirs** (`services/<name> [2|3]/`) are untracked and harmless
   (no `pyproject.toml`, skipped by installers/pytest); a separate cleanup could
   remove them.
6. **mypy present but not gated** by `make lint` (existing repo design: lint =
   ruff + black). Wiring mypy into CI is out of scope here.

---

## 6. Final recommendation

**APPROVE WITH MINOR FIXES.**

Bootstrap, environment isolation, interpreter validation, local + service
package installation, pre-commit, onboarding docs, and `make test` are all fixed
and verified on a fresh clone (`make test` → 840 passed / 16 skipped; imports
incl. `emg_identity`/`cryptography` OK; idempotent re-runs). The single
outstanding item is **pre-existing** whitespace-only Black nonconformance in 6
application files that makes `make lint` exit non-zero; resolving it (`make fmt`)
touches application code owned by other teams and should be a small, separately
approved follow-up rather than folded into this bootstrap-only sprint.

**Not committed, not pushed, not merged.** No frozen backlog item changed.
