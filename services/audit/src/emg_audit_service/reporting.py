"""Backend report serialization for the Audit Query & Reporting Interface
(FEAT-04-4, Sprint 8).

Two output formats, both backend-only (no HTML, no UI): JSON (the default,
FastAPI serializes the view models directly — unaffected by anything in this
module) and CSV (rendered here). The CSV writer emits a fixed, documented
column order so a downstream consumer gets a stable schema.

**CSV formula-injection neutralization (Sprint 8 security-review fix).** Several
CSV columns carry producer-supplied free text (`actor`, `reason`,
`transfer_reason`, `custodian`, `prior_custodian`, `evidence_id`,
`correlation_id`, ...). A cell whose first character is `=`, `+`, `-`, `@`, a
tab, or a carriage return is interpreted as a formula by common spreadsheet
applications (Excel, Google Sheets, LibreOffice) when the CSV is opened,
enabling formula-injection attacks (e.g. remote content fetch, or on some
older/misconfigured setups, command execution) against whoever opens the
export. `_neutralize_csv_cell` prefixes such a cell with a single quote `'`,
which spreadsheet applications render as a literal leading character rather
than executing it, while the plain-text CSV value itself (and every downstream
consumer that just reads the field) still sees the original value with the `'`
prefix as an ordinary leading character. This is a **presentation-layer**
neutralization applied only when rendering the CSV response body: it does not
touch the stored `AuditEvent`/`CustodyEvent` records, does not affect JSON
export (which serializes the same view models directly, unmodified), and does
not run at ingest/validation time.

There is no redaction step here beyond that: the persisted audit/custody
records were already validated and secret-redacted before they were stored
(`emg-audit-pipeline` validation), so a report simply reflects the safe stored
fields. This module intentionally has no access to raw tokens, secrets, or
authorization headers.

`collect_all` walks the full filtered result set via keyset pagination — one
store query per page (never per row), so building a report is not an N+1
operation. It is bounded by `EXPORT_MAX_ROWS` so an export can never allocate an
unbounded result set.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable

from emg_audit_client import (
    AuditEvent,
    AuditEventStore,
    AuditQuery,
    CustodyEvent,
    CustodyEventStore,
    CustodyQuery,
)
from emg_audit_pipeline import encode_cursor

from .schemas import AuditEventView, CustodyEventView

# One store query per page; bounded total so a report is neither N+1 nor
# unbounded in memory.
EXPORT_PAGE_SIZE = 1000
EXPORT_MAX_ROWS = 100_000

AUDIT_CSV_COLUMNS = [
    "sequence_number",
    "event_id",
    "source_principal",
    "timestamp",
    "correlation_id",
    "actor",
    "actor_type",
    "module",
    "action",
    "outcome",
    "resource_type",
    "resource_id",
    "classification",
    "source_system",
    "reason",
]

CUSTODY_CSV_COLUMNS = [
    "chain_sequence",
    "custody_sequence",
    "custody_event_id",
    "source_principal",
    "transfer_timestamp",
    "evidence_id",
    "custody_action",
    "custodian",
    "prior_custodian",
    "transfer_reason",
    "classification",
    "correlation_id",
]


def _isoformat(value: object) -> str:
    # datetimes render as ISO-8601; everything else via str(); None as "".
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    return str(value)


# Leading characters spreadsheet applications treat as the start of a formula.
_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _neutralize_csv_cell(value: str) -> str:
    """Neutralize CSV formula injection (Sprint 8 security-review fix): if
    `value` starts with `=`, `+`, `-`, `@`, a tab, or a carriage return, prefix
    it with a single quote `'` so a spreadsheet application treats it as a
    literal value rather than a formula. The original visible value is
    preserved unchanged after the prefix. Applied only to the rendered CSV
    cell — the stored record and the JSON export are untouched."""
    if value and value[0] in _FORMULA_TRIGGER_CHARS:
        return f"'{value}"
    return value


def audit_events_to_csv(events: list[AuditEventView]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(AUDIT_CSV_COLUMNS)
    for event in events:
        writer.writerow(
            [_neutralize_csv_cell(_isoformat(getattr(event, col))) for col in AUDIT_CSV_COLUMNS]
        )
    return buffer.getvalue()


def custody_events_to_csv(events: list[CustodyEventView]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CUSTODY_CSV_COLUMNS)
    for event in events:
        writer.writerow(
            [_neutralize_csv_cell(_isoformat(getattr(event, col))) for col in CUSTODY_CSV_COLUMNS]
        )
    return buffer.getvalue()


def collect_all_audit(
    store: AuditEventStore,
    base: AuditQuery,
    to_view: Callable[[AuditEvent], AuditEventView],
) -> list[AuditEventView]:
    """Page through every audit event matching `base` (ignoring its cursor/limit)
    via keyset pagination and return the safe view models, bounded by
    `EXPORT_MAX_ROWS`."""
    out: list[AuditEventView] = []
    cursor: str | None = None
    while True:
        page_query = base.model_copy(update={"cursor": cursor, "limit": EXPORT_PAGE_SIZE})
        page = store.query(page_query)
        out.extend(to_view(event) for event in page)
        if len(page) < EXPORT_PAGE_SIZE or len(out) >= EXPORT_MAX_ROWS:
            break
        cursor = encode_cursor(page[-1].sequence_number)
    return out[:EXPORT_MAX_ROWS]


def collect_all_custody(
    store: CustodyEventStore,
    base: CustodyQuery,
    to_view: Callable[[CustodyEvent], CustodyEventView],
) -> list[CustodyEventView]:
    """Page through every custody event matching `base` via keyset pagination."""
    out: list[CustodyEventView] = []
    cursor: str | None = None
    while True:
        page_query = base.model_copy(update={"cursor": cursor, "limit": EXPORT_PAGE_SIZE})
        page = store.query(page_query)
        out.extend(to_view(event) for event in page)
        if len(page) < EXPORT_PAGE_SIZE or len(out) >= EXPORT_MAX_ROWS:
            break
        cursor = encode_cursor(page[-1].chain_sequence)
    return out[:EXPORT_MAX_ROWS]
