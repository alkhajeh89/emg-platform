"""Migration discovery, checksums, and filename parsing (Phase 2, Sprint 2).

Pure and database-free: reads migration files from a directory, computes their
SHA-256 checksums, and returns ordered, validated :class:`Migration` objects.

Filename conventions (forward-only, ``version`` is the ordering key):

* PostgreSQL: ``V<version>__<name>.sql``   e.g. ``V001__baseline.sql``
* Neo4j:      ``M<version>__<name>.cypher`` e.g. ``M001__constraints.cypher``
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .errors import MigrationDiscoveryError
from .model import Migration, MigrationKind

_FILENAME_RE: dict[MigrationKind, re.Pattern[str]] = {
    MigrationKind.POSTGRES: re.compile(r"^V(?P<version>\d+)__(?P<name>[A-Za-z0-9._+-]+)\.sql$"),
    MigrationKind.NEO4J: re.compile(r"^M(?P<version>\d+)__(?P<name>[A-Za-z0-9._+-]+)\.cypher$"),
}
_EXTENSION: dict[MigrationKind, str] = {
    MigrationKind.POSTGRES: ".sql",
    MigrationKind.NEO4J: ".cypher",
}


def sha256_hex(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def parse_migration_filename(filename: str, kind: MigrationKind) -> tuple[int, str] | None:
    """Return ``(version, name)`` if ``filename`` matches the convention for
    ``kind``; otherwise ``None``."""
    match = _FILENAME_RE[kind].match(filename)
    if match is None:
        return None
    return int(match.group("version")), match.group("name")


def discover_migrations(directory: Path, kind: MigrationKind) -> tuple[Migration, ...]:
    """Return the migrations in ``directory`` for ``kind``, ordered by version.

    Files with the target extension that do not match the naming convention are
    treated as malformed (raise), so a mistyped migration name is never silently
    ignored. Files with other extensions (READMEs, ``.keep``) are ignored.

    Raises:
        MigrationDiscoveryError: missing directory, malformed filename, or a
            duplicate version number.
    """
    if not directory.is_dir():
        raise MigrationDiscoveryError(f"migration directory not found: {directory}")

    by_version: dict[int, Migration] = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix != _EXTENSION[kind]:
            continue
        parsed = parse_migration_filename(path.name, kind)
        if parsed is None:
            raise MigrationDiscoveryError(
                f"malformed {kind.value} migration filename: {path.name!r}"
            )
        version, name = parsed
        if version in by_version:
            raise MigrationDiscoveryError(
                f"duplicate {kind.value} migration version {version} "
                f"({by_version[version].name!r} and {name!r})"
            )
        data = path.read_bytes()
        by_version[version] = Migration(
            version=version,
            name=name,
            kind=kind,
            statements=data.decode("utf-8"),
            checksum=sha256_hex(data),
        )
    return tuple(by_version[v] for v in sorted(by_version))
