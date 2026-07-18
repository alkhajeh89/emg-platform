# Repository location & cloud sync — a hard developer guardrail

**Rule (non-negotiable):** never place a working clone of this repository inside
a cloud-synced folder — **iCloud Drive** (including `~/Documents` and `~/Desktop`
when "Desktop & Documents Folders" sync is enabled), **Dropbox**, **OneDrive**,
**Google Drive**, or any equivalent. Keep it under an unsynced path such as
`~/Developer/`, `~/src/`, or `~/dev/`.

This is not a style preference. Cloud-sync daemons race the filesystem against
`git`, `pip`, and `python -m venv`, and cause two concrete, hard-to-diagnose
failure modes that this project has already hit.

## Failure mode 1 — editable installs silently stop importing

macOS iCloud sets the BSD **`UF_HIDDEN`** file flag on files as it
materialises/re-syncs them. CPython's `site.py` (`addpackage()`) skips **any**
`.pth` file whose inode carries `UF_HIDDEN`, printing nothing unless you run
`python -v`:

```
Skipping hidden .pth file: '.../_emg_common_types.pth'
```

Because hatchling's editable installs work by writing a `.pth` file into
site-packages, a hidden flag on that file makes the package **unimportable**
even though `pip show` reports it correctly installed, `direct_url.json` is
correct, the `.pth` path is correct, and the target directory exists. The flag
is applied indiscriminately, so *unrelated* third-party `.pth` files (e.g.
`distutils-precedence.pth`) are skipped too — the tell that the cause is the
filesystem, not packaging. See
`docs/engineering/editable-install-troubleshooting.md` for the full CPython
mechanism.

**Symptoms:** every internal `emg_*` import fails with `ModuleNotFoundError`
while external packages import fine; `make test` collects 0 tests; imports work
only after a manual `sys.path.insert`.

**If you are already stuck in this state** (and cannot immediately relocate):
```bash
chflags -R nohidden .venv                     # clear the hidden flag
python -v -c "pass" 2>&1 | grep -i "hidden"   # confirm none are skipped now
```
This is a stopgap. The flag will be re-applied by the sync daemon; the only
durable fix is to move the repository out of the synced tree.

## Failure mode 2 — conflict-copy directories pollute the tree

When a sync daemon sees concurrent writes (very common during `pip install`,
`pytest`, or a branch switch), it creates **conflict-copy duplicates** with a
numeric suffix: `libs/python 3`, `services/audit 3`, `services/knowledge-graph
2`, and so on. These are byte-copies that can shadow or duplicate real work,
confuse tooling, and bloat the tree. This repository accumulated eight such
empty directories while hosted under iCloud; they were removed in Phase 0 and
are now guarded against in `.gitignore` (patterns `* [0-9]`, `* [0-9].*`,
`*.icloud`, `*conflicted copy*`, `*-DESKTOP-*`).

## Correct setup

```bash
# 1. Clone/keep the repo OUTSIDE any synced folder
mkdir -p ~/Developer && cd ~/Developer
git clone <emg-platform remote> emg-platform
cd emg-platform

# 2. Bootstrap normally (creates .venv on a supported interpreter, installs
#    all editable packages, git hooks)
make bootstrap

# 3. Verify the environment (also runs the editable-install integrity check)
make setup-check
```

## Why this belongs in engineering docs, not just tribal knowledge

The two failure modes above cost significant investigation time precisely
because every layer that engineers normally suspect — pip, hatchling, the `.pth`
contents, the interpreter, `pyproject.toml` — was correct. The root cause lived
entirely in the filesystem attributes applied by an external process. Writing it
down converts a multi-day debugging saga into a one-line rule for the next
engineer.

## Related

- `docs/engineering/editable-install-troubleshooting.md` — the exact `site.py`
  `.pth`-processing mechanism and a diagnostic script.
- `tools/scripts/diagnose_editable_installs.py` — reproduces `site.py`'s
  algorithm and reports why a specific editable package fails to import.
- `docs/engineering/onboarding.md` — first-clone setup.
