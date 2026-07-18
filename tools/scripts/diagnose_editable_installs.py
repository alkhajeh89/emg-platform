#!/usr/bin/env python3
"""Editable-install integrity diagnostic.

Root-cause context (see docs/engineering/editable-install-troubleshooting.md):
CPython's `site.py` processes each `*.pth` file in site-packages line by line
(Lib/site.py, `addpackage()`). For every non-comment, non-"import "-prefixed
line it does, in effect:

    dir = line.rstrip()
    if dir not in known_paths and os.path.exists(dir):
        sys.path.append(dir)

That `os.path.exists(dir)` check is the ONLY gate. If it is False, the
directory is dropped SILENTLY: no exception, no warning, nothing printed.
There is exactly one other silent-failure mode, in `addsitedir()` itself:
if the site-packages directory it is given does not resolve (e.g. a relative
path evaluated against the wrong cwd), `os.listdir()` raises `OSError`, which
`addsitedir()` catches and swallows, again with zero output.

Hatchling's default (non-`dev-mode-exact`) editable install writes exactly
one of these plain-path lines per package (this repo does not use
`dev-mode-exact` anywhere — verified by grep). So for a package that "pip
show" reports as correctly, editably installed, yet fails to import, the
fault is provably one of:

  1. The line's path string is not byte-identical to the real, current
     directory on disk (stray whitespace/BOM/quoting, or a path that was
     valid at install time but has since gone stale — e.g. the repository
     was moved/re-cloned/re-mounted to a different absolute location after
     the last successful `pip install -e`).
  2. Something upstream of site.py's normal per-interpreter-startup
     processing never called `addsitedir()` on this venv's real
     site-packages directory at all (wrong interpreter/venv actually
     running, `PYTHONNOUSERSITE`/`-S`/`-I`, or a corrupted `pyvenv.cfg`).

This script reproduces site.py's exact algorithm against every `.pth` file
on this interpreter's OWN site-packages path(s) (as this interpreter itself
would resolve them — no relative-path guessing) and reports, per local
package, exactly which of the two failure classes (if any) is in play,
instead of a bare ModuleNotFoundError.

Usage:  <venv>/bin/python tools/scripts/diagnose_editable_installs.py
Exit code: 0 if every local package resolves cleanly, 1 otherwise.
"""

from __future__ import annotations

import importlib
import re
import site
import sys
import sysconfig
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

try:
    import tomllib  # Python >= 3.11 (stdlib)
except ModuleNotFoundError:  # Python 3.10 target still supported by this repo
    tomllib = None  # type: ignore[assignment]


def _site_packages_dirs() -> list[Path]:
    """Every site-packages directory THIS running interpreter actually uses.

    Uses the same APIs site.py itself uses at startup (sysconfig/site), not a
    hand-typed path, so this can never suffer the relative-path/cwd pitfall
    that a manual `site.addsitedir(".venv/.../site-packages")` call can.
    """
    dirs: list[Path] = []
    if hasattr(site, "getsitepackages"):
        with suppress(OSError):
            dirs.extend(Path(p) for p in site.getsitepackages())

    purelib = sysconfig.get_path("purelib")
    if purelib:
        dirs.append(Path(purelib))
    seen: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        key = str(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _parse_pth_like_site_py(pth: Path) -> list[tuple[int, str, bool, bool]]:
    """(line_no, path_or_stmt, is_import_line, exists) for each real line,
    mirroring Lib/site.py `addpackage()` line-by-line, byte-for-byte."""
    out: list[tuple[int, str, bool, bool]] = []
    raw = pth.read_bytes()
    text = raw.decode(sys.getfilesystemencoding(), errors="surrogateescape")
    for n, line in enumerate(text.splitlines(), start=1):
        if line.startswith("#") or line.strip() == "":
            continue
        if line.startswith(("import ", "import\t")):
            out.append((n, line, True, False))
            continue
        candidate = line.rstrip()
        out.append((n, candidate, False, Path(candidate).exists()))
    return out


_NAME_RE = re.compile(r'(?m)^\s*name\s*=\s*"([^"]+)"\s*$')
_PACKAGES_RE = re.compile(r'(?m)^\s*packages\s*=\s*\[\s*"([^"]+)"')


def _parse_pyproject_fallback(text: str) -> dict:
    """Minimal, scoped extraction of just the two keys this script needs
    (`[project].name` and `[tool.hatch.build.targets.wheel].packages`), used
    only when `tomllib`/`tomli` is unavailable (Python 3.10). Not a general
    TOML parser — deliberately narrow, matching this repo's uniform,
    single-line pyproject.toml style.
    """
    project_section = text.split("[project]", 1)[1] if "[project]" in text else ""
    # Stop at the next top-level table so we don't pick up an unrelated `name`.
    project_section = re.split(r"(?m)^\[", project_section)[0]
    name_match = _NAME_RE.search(project_section)

    wheel_marker = "[tool.hatch.build.targets.wheel]"
    wheel_section = text.split(wheel_marker, 1)[1] if wheel_marker in text else ""
    wheel_section = re.split(r"(?m)^\[", wheel_section)[0]
    packages_match = _PACKAGES_RE.search(wheel_section)

    return {
        "project": {"name": name_match.group(1) if name_match else ""},
        "tool": {
            "hatch": {
                "build": {
                    "targets": {
                        "wheel": {"packages": [packages_match.group(1)] if packages_match else []}
                    }
                }
            }
        },
    }


def _load_pyproject(pyproject: Path) -> dict:
    if tomllib is not None:
        with pyproject.open("rb") as fh:
            return tomllib.load(fh)
    return _parse_pyproject_fallback(pyproject.read_text(encoding="utf-8"))


def _local_packages() -> list[tuple[str, str, Path]]:
    """(dist_name, import_name, expected_src_dir) for every libs/services pkg.

    Both names are read from the package's OWN pyproject.toml metadata, not
    guessed from its repository directory name — those two diverge for the
    `services/*` packages (directory `services/audit` ships distribution
    `emg-audit-service`, importable as `emg_audit_service`; directory
    `services/identity` ships `emg-identity`, importable as `emg_identity`).
    Guessing from the directory name is exactly the bug this function used
    to have: it derived `import audit` / `import identity` instead of the
    real `emg_audit_service` / `emg_identity`.
    """
    result = []
    for pyproject in sorted((ROOT / "libs" / "python").glob("*/pyproject.toml")) + sorted(
        (ROOT / "services").glob("*/pyproject.toml")
    ):
        pkg_dir = pyproject.parent
        data = _load_pyproject(pyproject)
        dist_name = data.get("project", {}).get("name") or pkg_dir.name

        packages = (
            data.get("tool", {})
            .get("hatch", {})
            .get("build", {})
            .get("targets", {})
            .get("wheel", {})
            .get("packages", [])
        )
        if packages:
            # e.g. "src/emg_audit_service" -> import name "emg_audit_service",
            # expected dir = pkg_dir / "src" / "emg_audit_service" (exactly
            # what hatchling's `packages = [...]` entry declares — not an
            # assumption derived from the directory name).
            rel = packages[0]
            import_name = Path(rel).name
            expected_src = pkg_dir / rel
        else:
            # No `packages` entry found (unexpected for this repo's uniform
            # layout) — fall back to the normalized dist name, but this is a
            # degraded guess, not the metadata-driven path above.
            import_name = dist_name.replace("-", "_")
            expected_src = pkg_dir / "src" / import_name

        result.append((dist_name, import_name, expected_src))
    return result


def main() -> int:
    sp_dirs = _site_packages_dirs()
    print(f"Interpreter:     {sys.executable}")
    print(f"Site-packages:   {', '.join(str(d) for d in sp_dirs) or '(none found)'}")
    print()

    problems = 0
    for dist_name, import_name, expected_src in _local_packages():
        # Hatchling/pip normalize the distribution name (PEP 503: lowercase,
        # runs of "-_." collapsed to a single separator) when naming the
        # generated .pth/finder files, so match against the import name, the
        # raw dist name, AND the underscore-normalized dist name.
        normalized_dist = re.sub(r"[-_.]+", "_", dist_name.lower())
        candidates_names = {import_name, dist_name, normalized_dist}
        pth_candidates: list[Path] = []
        for sp in sp_dirs:
            if not sp.is_dir():
                continue
            for pth in sp.glob("*.pth"):
                if any(name in pth.name for name in candidates_names):
                    pth_candidates.append(pth)

        if not pth_candidates:
            print(f"[{dist_name}] no .pth file found under any known site-packages dir")
            problems += 1
            continue

        pkg_ok = True
        for pth in pth_candidates:
            for n, payload, is_import, exists in _parse_pth_like_site_py(pth):
                if is_import:
                    print(f"[{dist_name}] {pth.name}:{n} is an exec('import ...') line, not a path")
                    continue
                if exists:
                    continue
                pkg_ok = False
                print(f"[{dist_name}] {pth.name}:{n} -> path does NOT exist:")
                print(f"    literal bytes: {payload.encode('unicode_escape')!r}")
                print(f"    expected dir : {expected_src}")
                print(f"    expected dir exists on disk: {expected_src.exists()}")
                if expected_src.exists() and payload != str(expected_src):
                    print(
                        "    DIAGNOSIS: the .pth entry does not match the real, current "
                        "source directory. This is a STALE absolute path baked in at a "
                        "previous `pip install -e` (e.g. the repository was moved, "
                        "re-cloned, or re-mounted to a different location since). Fix: "
                        "re-run `./tools/scripts/install-libs.sh` (or install-services.sh) "
                        "so hatchling re-emits the .pth with the CURRENT path — this is "
                        "not a workaround, it is the correct response to a path that has "
                        "legitimately changed since the last install."
                    )
                elif not expected_src.exists():
                    print(
                        "    DIAGNOSIS: neither the recorded nor the expected directory "
                        "exists. The package's src/ layout or name may not match its "
                        "pyproject.toml `packages = [...]` entry."
                    )
                else:
                    print(
                        "    DIAGNOSIS: the recorded path points at the CORRECT directory "
                        "but fails os.path.exists() anyway -- this means the on-disk bytes "
                        "of the .pth line are NOT identical to the real path string (stray "
                        "whitespace, BOM, quoting, or non-ASCII normalization). Run: "
                        f"xxd {pth} | head -5   to inspect the raw bytes."
                    )

        try:
            importlib.import_module(import_name)
            status = "import OK"
        except Exception as exc:  # noqa: BLE001 - deliberately broad; this is a diagnostic
            pkg_ok = False
            status = f"import FAILED -> {exc!r}"
        print(f"[{dist_name}] {status}")
        if not pkg_ok:
            problems += 1
        print()

    if problems:
        print(f"RESULT: {problems} package(s) with a broken editable install.")
        print("Permanent fix (not a blanket venv rebuild): re-run the install scripts so")
        print("hatchling re-emits .pth files against the CURRENT repository path:")
        print("    ./tools/scripts/install-libs.sh && ./tools/scripts/install-services.sh")
        return 1

    print("RESULT: every local package's editable install resolves cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
