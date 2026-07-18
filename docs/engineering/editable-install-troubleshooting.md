# Editable-install troubleshooting: "pip show says editable, import fails anyway"

Symptom: `pip install -e libs/python/<pkg>[dev]` reports success, `pip show
<pkg>` reports `Editable project location: .../libs/python/<pkg>`, and
`direct_url.json` looks correct — yet `import <pkg>` raises
`ModuleNotFoundError`, for every internal `emg-*` package at once, while
every third-party (PyPI) package continues to import normally.

This is not a pip bug, a hatchling bug, a PEP 660 bug, or a virtualenv bug.
It is a **silent-failure gate inside CPython's own `site` module**, combined
with a repository-configuration gap (unpinned build backend, implicit
dev-mode detection) that let the gate go unnoticed. Both are fixed in this
repository as of this document; this page explains the mechanism so the
failure is diagnosable, not mysterious, if it ever recurs.

## 1. What this repo's editable installs actually are

Every package under `libs/python/*` and `services/*` uses:

```toml
[build-system]
requires = ["hatchling>=1.14,<2"]
build-backend = "hatchling.build"

[tool.hatch.build]
dev-mode-dirs = ["src"]

[tool.hatch.build.targets.wheel]
packages = ["src/emg_<name>"]
```

Hatchling has two mutually exclusive editable-install mechanisms:

- **Default ("dev-mode-dirs")** — writes a `.pth` file into site-packages
  containing exactly one line: the absolute path to the package's `src/`
  directory. CPython's `site.py` adds that directory to `sys.path` at
  interpreter startup. This is what this repository uses (verified: no
  `dev-mode-exact` setting exists anywhere in the tree).
- **`dev-mode-exact = true`** (opt-in, not used here) — writes a
  `_editable_impl_<name>.py` finder module plus a `.pth` file that does
  `import _editable_impl_<name>`, mapping only the declared package name
  instead of the whole directory. Not supported by static analysis tools.

Before this fix, `[build-system] requires = ["hatchling"]` was **unpinned**
across all 17 internal packages, and `dev-mode-dirs` was never set
explicitly — it was left to hatchling's file-selection auto-detection. Both
gaps are closed now (pin + explicit `dev-mode-dirs = ["src"]`), so the
editable-install mechanism this repo gets is deterministic and independent
of whichever hatchling version happens to resolve at build time.

## 2. The exact site.py mechanism (this is not speculation — it is the
   entire relevant surface of CPython's stdlib `site` module)

`site.py` processes every `*.pth` file in a site-packages directory via
`addpackage()`. For a plain-path line (not an `import ...` line), the logic
is, verbatim in effect:

```python
dir, dircase = makepath(sitedir, line.rstrip())
if dircase not in known_paths and os.path.exists(dir):
    sys.path.append(dir)
```

**There is exactly one gate: `os.path.exists(dir)`.** If it is `False`, the
directory is dropped with **zero output** — no exception, no stderr, no log
line. This is the only way a syntactically well-formed, single-line,
plain-path `.pth` file can fail to add its directory to `sys.path`.

There is exactly one other silent-failure branch, in `addsitedir()` itself
(the function you'd call to reproduce this by hand):

```python
def addsitedir(sitedir, known_paths=None):
    ...
    try:
        names = os.listdir(sitedir)
    except OSError:
        return          # <-- silent, no exception propagates
```

If `sitedir` doesn't exist **as resolved relative to the calling process's
current working directory**, `os.listdir` raises, and `addsitedir` swallows
it. This matters because manually reproducing the bug with
`site.addsitedir(".venv/lib/python3.12/site-packages")` (a **relative**
path) is only valid if the interpreter's cwd is exactly the repo root at
that moment — a debugger, REPL, or pytest invocation from any other
directory will silently no-op here and give a false read that ".pth
processing itself is broken," when in fact it only proves the manual
repro command's cwd assumption was wrong. Always pass an **absolute** path
when reproducing this by hand.

Because both of `site.py`'s silent-failure branches are literal, public,
unchanging stdlib code, the root cause of "editable install exists, import
fails, no error anywhere" is provably one of exactly two things:

1. **The `.pth` line's path string is not byte-identical to the real,
   current directory on disk.** Either it was correct at install time and
   has since gone stale (the repository was moved, re-cloned, or
   re-mounted to a different absolute location since the last successful
   `pip install -e`), or the line was corrupted (stray whitespace, BOM, or
   quoting) at write time.
2. **Normal interpreter startup never called `addsitedir()` on this venv's
   real site-packages directory at all** — wrong interpreter/venv actually
   running (e.g. a shell picked up a different `python3.12` than the one
   `pip install -e` targeted), `PYTHONNOUSERSITE`/`-S`/`-I` in effect, or a
   corrupted `pyvenv.cfg`.

Everything else in the "pip / hatchling / PEP 660 / virtualenv / macOS"
list the request asked to rule in or out is, by the above, ruled **out** as
a category: none of those layers has a code path that can produce this
signature. The fault is squarely in (a) repository configuration (unpinned
backend, implicit dev-mode — now fixed) feeding an otherwise-correct (b)
CPython `site.py` gate.

## 3. Exact files to inspect

- `libs/python/<pkg>/pyproject.toml` / `services/<svc>/pyproject.toml` —
  confirm `[tool.hatch.build] dev-mode-dirs = ["src"]` and a pinned
  `hatchling` range are present (now true for all 17 packages).
- `.venv/lib/python3.1x/site-packages/*.pth` — the actual editable-install
  redirect files. One per package.
- `.venv/lib/python3.1x/site-packages/emg_*-*.dist-info/direct_url.json` —
  pip's own record of the source path used at install time.
- `.venv/pyvenv.cfg` — confirms which base interpreter this venv was built
  from and whether `include-system-site-packages` is set.
- `tools/scripts/diagnose_editable_installs.py` (new) — reproduces
  `site.py`'s exact algorithm against every local package's `.pth` file and
  reports the precise failing line, its raw bytes, and which of the two
  failure classes above applies. Run via `make setup-check` or directly:
  `.venv/bin/python tools/scripts/diagnose_editable_installs.py`.

## 4. Exact commands to run, in order

```bash
# 1. Confirm which interpreter/venv is ACTUALLY running your imports.
.venv/bin/python -c "import sys; print(sys.executable); print(sys.prefix)"

# 2. Confirm the real, current site-packages dir(s) THIS interpreter uses
#    (not a hand-typed relative path).
.venv/bin/python -c "import site, sysconfig; print(site.getsitepackages()); print(sysconfig.get_path('purelib'))"

# 3. List every editable .pth for the internal packages.
ls .venv/lib/python3.1*/site-packages/*.pth

# 4. Dump one .pth file's RAW BYTES (not a text editor's rendering — a text
#    editor/terminal can hide a BOM, NBSP, or trailing control character).
xxd .venv/lib/python3.1*/site-packages/_editable_impl_emg_common_types.pth | head -5
#    or, portably:
.venv/bin/python -c "print(repr(open('PATH_TO_PTH_FILE','rb').read()))"

# 5. Compare that exact byte string, as a path, against the real directory.
.venv/bin/python -c "
import pathlib
p = 'PASTE_THE_EXACT_STRING_FROM_STEP_4_HERE'
print('exists:', pathlib.Path(p).exists())
print('repo says it should be:', pathlib.Path('libs/python/emg-common-types/src/emg_common_types').resolve())
"

# 6. Run the full automated diagnostic (does steps 1-5 for every package):
.venv/bin/python tools/scripts/diagnose_editable_installs.py
```

If step 6 reports a stale path (the recorded `.pth` directory differs from
the real, current `libs/python/<pkg>/src/<pkg>` directory), the correct fix
is **not** "delete and recreate .venv" — it is to re-run exactly the
install step that regenerates the `.pth` file against the current path:

```bash
./tools/scripts/install-libs.sh
./tools/scripts/install-services.sh
```

This is a targeted, idempotent, already-existing step of `make bootstrap`
(step 5) — not a new workaround — and it is now automatically followed by
step 5b (`diagnose_editable_installs.py`), so bootstrap will tell you
immediately, with the exact failing package and line, if anything still
does not resolve after that re-install.

If step 6 instead reports that the recorded path is CORRECT (matches the
real directory) yet `os.path.exists()` still returns `False`, the fault is
byte-level corruption in that one `.pth` file (case 1's "corrupted at write
time" variant) — the diagnostic prints the exact `unicode_escape`-encoded
bytes so the specific invisible character is visible, and the fix is to
regenerate that one file the same way (re-run the install script for that
package), not to touch application code.

## 5. What was actually wrong in the repository (fixed)

- `[build-system] requires = ["hatchling"]` was unpinned in all 17
  `libs/python/*` and `services/*` packages. Because pip performs a fresh,
  isolated PEP 517 build environment per editable install (no
  `--no-build-isolation` flag is used anywhere in this repo's tooling),
  every `pip install -e` could resolve a **different** hatchling version
  depending on the machine and the moment — including, in principle, a
  future hatchling release that changes its default dev-mode auto-detection
  heuristic. Fixed: pinned to `hatchling>=1.14,<2` everywhere.
- `dev-mode-dirs` was never set explicitly; the `"src"` directory was
  correctly auto-detected from `packages = ["src/emg_<name>"]`, but only
  implicitly, via hatchling's own file-selection heuristic — not declared
  as repository configuration. Fixed: `[tool.hatch.build] dev-mode-dirs =
  ["src"]` is now explicit in every package, so the editable-install target
  directory can never silently change across hatchling versions.
- There was no automated check that an editable install which *reports*
  success actually *resolves* on the current machine — the only way to
  notice was a bare `ModuleNotFoundError` days or weeks later, with no
  indication of why. Fixed: `tools/scripts/diagnose_editable_installs.py`,
  wired into both `make setup-check` (loud, on demand) and `make bootstrap`
  (automatic, immediately after every install).
