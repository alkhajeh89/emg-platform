"""HTTP-level tests for the Audit Query & Reporting Interface (FEAT-04-4).

Covers the richer classification-aware audit filters, stable opaque-cursor
keyset pagination (deterministic order, no duplicates, no skipped records),
JSON + CSV export for both the audit and custody surfaces, custody querying,
report-walk performance (bounded, not N+1), authorization (svc-audit-only),
backward compatibility of the Sprint 6 query shape, CSV formula-injection
neutralization (Sprint 8 security-review fix), export field-exposure guards,
and export enum validation.
"""

from __future__ import annotations

import csv
import io
import time

import jwt


def issue_service_token(
    settings,
    private_key,
    *,
    client_id: str,
    scope: str,
    exp_delta: int = 300,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iat": now,
            "exp": now + exp_delta,
            "iss": settings.keycloak_issuer,
            "aud": settings.service_token_audience,
            "azp": client_id,
            "scope": scope,
        },
        private_key,
        algorithm="RS256",
    )


def _ingest_token(settings, rsa_keypair) -> str:
    private_key, _ = rsa_keypair
    return issue_service_token(
        settings, private_key, client_id="emg-svc-identity", scope="svc-identity"
    )


def _reader_token(settings, rsa_keypair) -> str:
    private_key, _ = rsa_keypair
    return issue_service_token(settings, private_key, client_id="emg-svc-audit", scope="svc-audit")


def _event(event_id: str, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "actor": "dev.investigator",
        "actor_type": "human",
        "module": "identity",
        "action": "login",
        "outcome": "success",
        "source_system": "identity",
    }
    payload.update(overrides)
    return payload


def _seed(client, settings, rsa_keypair, n: int, **overrides) -> None:
    h = {"Authorization": f"Bearer {_ingest_token(settings, rsa_keypair)}"}
    for i in range(n):
        resp = client.post("/audit/events", json=_event(f"evt-{i}", **overrides), headers=h)
        assert resp.status_code == 200


# --- backward compatibility -----------------------------------------------


def test_query_events_still_returns_a_list(client, settings, rsa_keypair):
    _seed(client, settings, rsa_keypair, 3)
    h = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    resp = client.get("/audit/events", headers=h)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 3


# --- new filters -----------------------------------------------------------


def test_filter_by_classification_and_module(client, settings, rsa_keypair):
    h = {"Authorization": f"Bearer {_ingest_token(settings, rsa_keypair)}"}
    client.post("/audit/events", json=_event("a", classification="SECRET"), headers=h)
    client.post("/audit/events", json=_event("b", module="authz"), headers=h)
    rh = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    secret = client.get("/audit/events", params={"classification": "SECRET"}, headers=rh).json()
    assert [e["event_id"] for e in secret] == ["a"]
    authz = client.get("/audit/events", params={"module": "authz"}, headers=rh).json()
    assert [e["event_id"] for e in authz] == ["b"]


def test_invalid_classification_returns_422(client, settings, rsa_keypair):
    rh = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    resp = client.get("/audit/events", params={"classification": "COSMIC"}, headers=rh)
    assert resp.status_code == 422


# --- cursor pagination -----------------------------------------------------


def test_page_walk_no_dupes_no_skips(client, settings, rsa_keypair):
    _seed(client, settings, rsa_keypair, 25)
    rh = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    seen: list[int] = []
    cursor = None
    for _ in range(100):  # safety bound
        params = {"limit": 10}
        if cursor:
            params["cursor"] = cursor
        page = client.get("/audit/events/page", params=params, headers=rh).json()
        seen.extend(item["sequence_number"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == list(range(1, 26))  # every record once, in order


def test_page_cursor_contract(client, settings, rsa_keypair):
    """Standard keyset contract: a short page (fewer than `limit`) ends the walk
    (next_cursor=None); a full page returns a cursor whose follow-up page is
    empty at the true end. Never a duplicate or skipped record either way."""
    _seed(client, settings, rsa_keypair, 5)
    rh = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    # limit > remaining -> short page, terminal.
    partial = client.get("/audit/events/page", params={"limit": 10}, headers=rh).json()
    assert partial["count"] == 5
    assert partial["next_cursor"] is None
    # limit == total -> full page, cursor set; following it yields an empty page.
    full = client.get("/audit/events/page", params={"limit": 5}, headers=rh).json()
    assert full["count"] == 5 and full["next_cursor"] is not None
    tail = client.get(
        "/audit/events/page", params={"limit": 5, "cursor": full["next_cursor"]}, headers=rh
    ).json()
    assert tail["count"] == 0 and tail["next_cursor"] is None


def test_invalid_cursor_returns_400(client, settings, rsa_keypair):
    _seed(client, settings, rsa_keypair, 1)
    rh = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    resp = client.get("/audit/events/page", params={"cursor": "not-a-cursor!!"}, headers=rh)
    assert resp.status_code == 400
    assert resp.json()["error"]["error_code"] == "CURSOR_INVALID"


# --- export: JSON + CSV ----------------------------------------------------


def test_export_json(client, settings, rsa_keypair):
    _seed(client, settings, rsa_keypair, 4)
    rh = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    resp = client.get("/audit/events/export", params={"format": "json"}, headers=rh)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list) and len(body) == 4
    assert [e["sequence_number"] for e in body] == [1, 2, 3, 4]


def test_export_csv(client, settings, rsa_keypair):
    _seed(client, settings, rsa_keypair, 3)
    rh = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    resp = client.get("/audit/events/export", params={"format": "csv"}, headers=rh)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0] == [
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
    assert len(rows) == 1 + 3  # header + 3 data rows


def test_export_csv_filtered(client, settings, rsa_keypair):
    h = {"Authorization": f"Bearer {_ingest_token(settings, rsa_keypair)}"}
    client.post("/audit/events", json=_event("a", outcome="denied"), headers=h)
    client.post("/audit/events", json=_event("b", outcome="success"), headers=h)
    rh = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    resp = client.get(
        "/audit/events/export", params={"format": "csv", "outcome": "denied"}, headers=rh
    )
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert len(rows) == 1 + 1  # header + only the denied row


def test_export_invalid_format_returns_422(client, settings, rsa_keypair):
    rh = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    resp = client.get("/audit/events/export", params={"format": "xml"}, headers=rh)
    assert resp.status_code == 422


# --- authorization: reader endpoints are svc-audit only --------------------


def test_page_requires_svc_audit(client, settings, rsa_keypair):
    assert client.get("/audit/events/page").status_code == 401
    # A non-audit principal (svc-identity) may ingest but must not read reports.
    ih = {"Authorization": f"Bearer {_ingest_token(settings, rsa_keypair)}"}
    assert client.get("/audit/events/page", headers=ih).status_code == 401
    assert client.get("/audit/events/export", headers=ih).status_code == 401


# --- custody reporting -----------------------------------------------------


def _custody(cid: str, **overrides) -> dict:
    payload = {
        "custody_event_id": cid,
        "evidence_id": "E1",
        "custody_action": "acquire",
        "custodian": "alice",
    }
    payload.update(overrides)
    return payload


def test_custody_page_and_export(client, settings, rsa_keypair):
    h = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    for i in range(7):
        client.post("/audit/custody/events", json=_custody(f"c-{i}"), headers=h)
    # Page walk.
    seen: list[int] = []
    cursor = None
    for _ in range(100):
        params = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        page = client.get("/audit/custody/events/page", params=params, headers=h).json()
        seen.extend(item["chain_sequence"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == list(range(1, 8))
    # CSV export.
    resp = client.get("/audit/custody/export", params={"format": "csv"}, headers=h)
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0][0] == "chain_sequence"
    assert len(rows) == 1 + 7


def test_custody_export_requires_svc_audit(client):
    assert client.get("/audit/custody/export").status_code == 401
    assert client.get("/audit/custody/events/page").status_code == 401


# --- performance: report walk is bounded (not N+1) -------------------------


class _CountingStore:
    def __init__(self, inner):
        self._inner = inner
        self.query_calls = 0

    def query(self, query):
        self.query_calls += 1
        return self._inner.query(query)


def test_report_walk_is_not_n_plus_1(monkeypatch):
    from emg_audit_client import AuditQuery, SubmittedAuditEvent
    from emg_audit_pipeline import InMemoryAuditEventStore
    from emg_audit_service import reporting
    from emg_audit_service.routers.events import _to_view

    inner = InMemoryAuditEventStore()
    for i in range(25):
        inner.append(
            SubmittedAuditEvent(
                event_id=f"e-{i}",
                actor="a",
                actor_type="service",
                module="identity",
                action="login",
                outcome="success",
                source_system="identity",
            ),
            source_principal="emg-svc-audit",
        )
    monkeypatch.setattr(reporting, "EXPORT_PAGE_SIZE", 10)
    counting = _CountingStore(inner)
    views = reporting.collect_all_audit(counting, AuditQuery(), _to_view)
    assert len(views) == 25
    # 25 rows / page 10 => 3 queries (10, 10, 5), never one query per row.
    assert counting.query_calls == 3


# --- CSV formula-injection neutralization (Sprint 8 security-review fix) ---


def test_neutralize_csv_cell_unit():
    """Direct unit coverage of the neutralization helper for every documented
    trigger character, plus a regression case proving normal cells pass
    through unchanged."""
    from emg_audit_service.reporting import _neutralize_csv_cell

    assert _neutralize_csv_cell("=SUM(1,1)") == "'=SUM(1,1)"
    assert _neutralize_csv_cell('+HYPERLINK("http://evil","click")') == (
        '\'+HYPERLINK("http://evil","click")'
    )
    assert _neutralize_csv_cell("-2+3") == "'-2+3"
    assert _neutralize_csv_cell("@SUM(1,1)") == "'@SUM(1,1)"
    assert _neutralize_csv_cell("\tstart") == "'\tstart"
    assert _neutralize_csv_cell("\rstart") == "'\rstart"
    # Regression: ordinary values, including a mid-string trigger character,
    # are left byte-for-byte unchanged.
    assert _neutralize_csv_cell("dev.investigator") == "dev.investigator"
    assert _neutralize_csv_cell("login") == "login"
    assert _neutralize_csv_cell("a - b = c") == "a - b = c"
    assert _neutralize_csv_cell("") == ""


def test_audit_csv_export_neutralizes_formula_injection(client, settings, rsa_keypair):
    """End-to-end: a producer-supplied `reason` value that looks like a
    spreadsheet formula is neutralized in the CSV export but not in the JSON
    export, and the stored record itself is never mutated."""
    h = {"Authorization": f"Bearer {_ingest_token(settings, rsa_keypair)}"}
    payloads = {
        "eq": "=SUM(1,1)",
        "plus": '+HYPERLINK("http://evil","click")',
        "minus": "-2+3",
        "at": "@SUM(1,1)",
        "tab": "\tstart",
        "cr": "\rstart",
    }
    for event_id, reason in payloads.items():
        resp = client.post("/audit/events", json=_event(event_id, reason=reason), headers=h)
        assert resp.status_code == 200

    rh = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}

    # CSV: every triggering value is prefixed with a single quote.
    csv_resp = client.get("/audit/events/export", params={"format": "csv"}, headers=rh)
    rows = list(csv.reader(io.StringIO(csv_resp.text)))
    header = rows[0]
    reason_idx = header.index("reason")
    by_id = {row[header.index("event_id")]: row[reason_idx] for row in rows[1:]}
    assert by_id["eq"] == "'=SUM(1,1)"
    assert by_id["plus"] == '\'+HYPERLINK("http://evil","click")'
    assert by_id["minus"] == "'-2+3"
    assert by_id["at"] == "'@SUM(1,1)"
    assert by_id["tab"] == "'\tstart"
    assert by_id["cr"] == "'\rstart"

    # JSON export is untouched: the original values are returned verbatim,
    # never prefixed.
    json_resp = client.get("/audit/events/export", params={"format": "json"}, headers=rh)
    json_by_id = {e["event_id"]: e["reason"] for e in json_resp.json()}
    for event_id, original in payloads.items():
        assert json_by_id[event_id] == original

    # The stored record itself was never mutated: the plain query endpoint
    # (not CSV) also returns the original, unprefixed value.
    query_by_id = {
        e["event_id"]: e["reason"] for e in client.get("/audit/events", headers=rh).json()
    }
    for event_id, original in payloads.items():
        assert query_by_id[event_id] == original


def test_audit_csv_export_normal_values_unchanged(client, settings, rsa_keypair):
    """Regression: an ordinary reason value is exported byte-for-byte
    unchanged (no spurious quote prefix)."""
    h = {"Authorization": f"Bearer {_ingest_token(settings, rsa_keypair)}"}
    client.post(
        "/audit/events", json=_event("normal", reason="scheduled maintenance login"), headers=h
    )
    rh = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    resp = client.get("/audit/events/export", params={"format": "csv"}, headers=rh)
    rows = list(csv.reader(io.StringIO(resp.text)))
    header = rows[0]
    reason_idx = header.index("reason")
    data_row = next(r for r in rows[1:] if r[header.index("event_id")] == "normal")
    assert data_row[reason_idx] == "scheduled maintenance login"


def test_custody_csv_export_neutralizes_formula_injection(client, settings, rsa_keypair):
    """Same neutralization, exercised on the separate custody CSV export and a
    different producer-controlled column (transfer_reason)."""
    h = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    payloads = {
        "c-eq": "=SUM(1,1)",
        "c-plus": '+HYPERLINK("http://evil","click")',
        "c-minus": "-2+3",
        "c-at": "@SUM(1,1)",
        "c-tab": "\tstart",
        "c-cr": "\rstart",
    }
    for cid, reason in payloads.items():
        resp = client.post(
            "/audit/custody/events", json=_custody(cid, transfer_reason=reason), headers=h
        )
        assert resp.status_code == 200

    resp = client.get("/audit/custody/export", params={"format": "csv"}, headers=h)
    rows = list(csv.reader(io.StringIO(resp.text)))
    header = rows[0]
    reason_idx = header.index("transfer_reason")
    by_id = {row[header.index("custody_event_id")]: row[reason_idx] for row in rows[1:]}
    assert by_id["c-eq"] == "'=SUM(1,1)"
    assert by_id["c-plus"] == '\'+HYPERLINK("http://evil","click")'
    assert by_id["c-minus"] == "'-2+3"
    assert by_id["c-at"] == "'@SUM(1,1)"
    assert by_id["c-tab"] == "'\tstart"
    assert by_id["c-cr"] == "'\rstart"

    # JSON export and the plain query endpoint keep the original values.
    json_by_id = {
        e["custody_event_id"]: e["transfer_reason"]
        for e in client.get("/audit/custody/export", params={"format": "json"}, headers=h).json()
    }
    for cid, original in payloads.items():
        assert json_by_id[cid] == original


def test_custody_csv_export_normal_values_unchanged(client, settings, rsa_keypair):
    h = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    client.post(
        "/audit/custody/events",
        json=_custody("normal-custody", transfer_reason="seized at scene"),
        headers=h,
    )
    resp = client.get("/audit/custody/export", params={"format": "csv"}, headers=h)
    rows = list(csv.reader(io.StringIO(resp.text)))
    header = rows[0]
    reason_idx = header.index("transfer_reason")
    data_row = next(r for r in rows[1:] if r[header.index("custody_event_id")] == "normal-custody")
    assert data_row[reason_idx] == "seized at scene"


# --- export field-exposure guards -------------------------------------------


def test_audit_page_and_export_do_not_expose_internal_fields(client, settings, rsa_keypair):
    """Neither the paginated view nor either export format leaks metadata,
    provenance, or hash-chain fields — those are internal/integrity fields,
    not part of the FEAT-04-4 reporting surface."""
    _seed(client, settings, rsa_keypair, 2)
    rh = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    forbidden = {"metadata", "provenance", "event_hash", "prev_hash"}

    page = client.get("/audit/events/page", headers=rh).json()
    for item in page["items"]:
        assert forbidden.isdisjoint(item.keys())

    json_export = client.get("/audit/events/export", params={"format": "json"}, headers=rh).json()
    for item in json_export:
        assert forbidden.isdisjoint(item.keys())

    csv_export = client.get("/audit/events/export", params={"format": "csv"}, headers=rh)
    header = next(csv.reader(io.StringIO(csv_export.text)))
    assert forbidden.isdisjoint(set(header))


def test_custody_page_and_export_do_not_expose_internal_fields(client, settings, rsa_keypair):
    h = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    client.post("/audit/custody/events", json=_custody("guard-1"), headers=h)
    forbidden = {"metadata", "provenance", "event_hash", "prev_hash"}

    page = client.get("/audit/custody/events/page", headers=h).json()
    for item in page["items"]:
        assert forbidden.isdisjoint(item.keys())

    json_export = client.get("/audit/custody/export", params={"format": "json"}, headers=h).json()
    for item in json_export:
        assert forbidden.isdisjoint(item.keys())

    csv_export = client.get("/audit/custody/export", params={"format": "csv"}, headers=h)
    header = next(csv.reader(io.StringIO(csv_export.text)))
    assert forbidden.isdisjoint(set(header))


# --- export enum validation --------------------------------------------------


def test_export_invalid_classification_returns_422(client, settings, rsa_keypair):
    rh = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    resp = client.get("/audit/events/export", params={"classification": "COSMIC"}, headers=rh)
    assert resp.status_code == 422


def test_export_invalid_outcome_returns_422(client, settings, rsa_keypair):
    rh = {"Authorization": f"Bearer {_reader_token(settings, rsa_keypair)}"}
    resp = client.get("/audit/events/export", params={"outcome": "maybe"}, headers=rh)
    assert resp.status_code == 422
