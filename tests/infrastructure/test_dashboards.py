"""RC-C (EMG v1 RC closure, P0 alerting): structural validity tests for the
Grafana dashboard JSON under observability/dashboards/.

No Grafana instance is available in this environment to import against (no
metrics backend is deployed by this repository -- see
observability/alerts/emg-platform-alerts.yaml's ARCHITECTURAL STOP note),
so these tests validate what is checkable without one: JSON validity, the
minimum field set Grafana's dashboard JSON model requires to import
successfully, UID/panel-ID uniqueness (a duplicate breaks import), and that
every PromQL `targets[].expr` references only metric names this repository
actually emits (the same "dashboards giving false confidence" adversarial
check applied to alerts in test_alert_rules.py, applied here to dashboards).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
DASHBOARDS_DIR = ROOT / "observability/dashboards"
DASHBOARD_FILES = sorted(DASHBOARDS_DIR.glob("*.json"))

_METRIC_TOKEN = re.compile(
    r"\b([a-zA-Z_:][a-zA-Z0-9_:]*(?:_total|_seconds|_bytes|_ready|_healthy|_status|_sum|_max))\b"
)
_INSTRUMENTED_METRIC_FILES = (
    ROOT / "libs/python/emg-telemetry/src/emg_telemetry/http_metrics.py",
    ROOT / "libs/python/emg-telemetry/src/emg_telemetry/metrics.py",
    ROOT / "services/knowledge-graph/src/emg_knowledge_graph_api/mutation_observability.py",
    ROOT / "services/knowledge-graph/src/emg_knowledge_graph_api/search_metrics.py",
    ROOT / "services/audit-projector/src/emg_audit_projector/telemetry.py",
    ROOT / "tools/backup/emit_metrics.py",
)
_METRIC_DECL = re.compile(r'"([a-zA-Z_:][a-zA-Z0-9_:]*)"')

_PROMQL_FUNCTIONS = {
    "sum",
    "rate",
    "increase",
    "histogram_quantile",
    "count",
    "time",
    "max",
    "min",
    "avg",
    "absent",
    "by",
    "on",
}


def _known_metric_names() -> set[str]:
    names: set[str] = set()
    for path in _INSTRUMENTED_METRIC_FILES:
        names.update(_METRIC_DECL.findall(path.read_text()))
    return names


def test_at_least_one_dashboard_exists_per_required_priority_area():
    """RC-C DASHBOARDS requirement: platform health, security/auth,
    mutation/audit pipelines, datastore/projection health, search health,
    recovery readiness."""
    required_tag_groups = [
        {"platform-health"},
        {"security", "auth"},
        {"audit", "mutation"},
        {"datastore", "projection"},
        {"search"},
        {"recovery", "backup"},
    ]
    all_tags: set[str] = set()
    for path in DASHBOARD_FILES:
        all_tags |= set(json.loads(path.read_text())["tags"])
    for required in required_tag_groups:
        assert required & all_tags, f"no dashboard covers required area {required}"


@pytest.mark.parametrize("path", DASHBOARD_FILES, ids=lambda p: p.name)
def test_dashboard_is_valid_json(path: Path):
    json.loads(path.read_text())


@pytest.mark.parametrize("path", DASHBOARD_FILES, ids=lambda p: p.name)
def test_dashboard_has_required_grafana_fields(path: Path):
    doc = json.loads(path.read_text())
    for field in ("uid", "title", "schemaVersion", "panels", "tags", "templating"):
        assert field in doc, f"{path.name} missing required field {field!r}"
    assert isinstance(doc["panels"], list) and len(doc["panels"]) > 0
    assert isinstance(doc["schemaVersion"], int)


@pytest.mark.parametrize("path", DASHBOARD_FILES, ids=lambda p: p.name)
def test_panel_ids_are_unique_within_a_dashboard(path: Path):
    doc = json.loads(path.read_text())
    ids = [panel["id"] for panel in doc["panels"]]
    assert len(ids) == len(set(ids)), f"{path.name} has duplicate panel ids"


def test_dashboard_uids_are_globally_unique():
    uids = [json.loads(path.read_text())["uid"] for path in DASHBOARD_FILES]
    assert len(uids) == len(set(uids))


@pytest.mark.parametrize("path", DASHBOARD_FILES, ids=lambda p: p.name)
def test_panel_targets_reference_only_metrics_this_repository_actually_emits(path: Path):
    doc = json.loads(path.read_text())
    known = _known_metric_names()
    for panel in doc["panels"]:
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            tokens = set(_METRIC_TOKEN.findall(expr)) - _PROMQL_FUNCTIONS
            unknown = {t for t in tokens if t not in known}
            assert (
                not unknown
            ), f"{path.name} panel {panel['title']!r} references unknown metric(s): {unknown}"


@pytest.mark.parametrize("path", DASHBOARD_FILES, ids=lambda p: p.name)
def test_no_tenant_entity_query_or_credential_content_in_any_panel_expr(path: Path):
    doc = json.loads(path.read_text())
    forbidden = ("tenant", "entity_id", "principal", "credential", "secret", "password", "dsn")
    for panel in doc["panels"]:
        for target in panel.get("targets", []):
            expr = target.get("expr", "").lower()
            for term in forbidden:
                assert term not in expr, f"{path.name} panel {panel['title']!r} references {term!r}"


@pytest.mark.parametrize("path", DASHBOARD_FILES, ids=lambda p: p.name)
def test_every_panel_has_a_gridpos_that_does_not_overlap_trivially(path: Path):
    """A minimal layout sanity check: every panel declares a gridPos (Grafana
    silently stacks panels at (0,0) without one, which is the "dashboard
    gives false confidence" failure mode of a panel nobody can actually see)."""
    doc = json.loads(path.read_text())
    for panel in doc["panels"]:
        assert "gridPos" in panel, f"{path.name} panel {panel.get('title')!r} has no gridPos"
        grid = panel["gridPos"]
        for key in ("x", "y", "w", "h"):
            assert key in grid and isinstance(grid[key], int)
