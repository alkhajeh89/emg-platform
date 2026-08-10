"""RC-C (EMG v1 RC closure, P0 alerting): structural/governance tests for
observability/alerts/emg-platform-alerts.yaml.

No `promtool` binary is available in this environment (not a repository
dependency), so these tests validate what is checkable without it: YAML
syntax, the required-field contract every P0/P1 alert must satisfy per the
RC-C task brief (severity, summary, description, runbook), balanced
PromQL expression syntax, and the privacy/cardinality/tenant-safety
properties the adversarial review requires (no tenant/entity/query/
principal/credential content in any expression or label). Also verified: no
alert claims to be implementable now (bucket A) while referencing a metric
name this repository does not actually emit anywhere in `services/` or
`libs/` -- this is the "alerts that can never fire because the metric does
not exist" adversarial check, checked mechanically rather than by
inspection alone.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[2]
ALERTS_PATH = ROOT / "observability/alerts/emg-platform-alerts.yaml"
RUNBOOK_PATH = ROOT / "docs/operations/alert-runbook.md"

_FORBIDDEN_LABEL_SUBSTRINGS = (
    "tenant",
    "entity_id",
    "principal",
    "query",
    "credential",
    "secret",
    "password",
    "dsn",
    "token",
)

# Groups whose expressions reference metrics this repository's code actually
# emits today (bucket A per the file's own group docstrings). Cluster/
# datastore groups reference standard third-party exporter metric names
# (kube-state-metrics/cAdvisor/postgres_exporter) that are explicitly out of
# scope for this check -- they are bucket B/C by design, and the file's own
# comments say so.
_BUCKET_A_GROUPS = {
    "emg-platform-availability",
    "emg-platform-http",
    "emg-audit-pipeline",
    "emg-mutation-pipeline",
    "emg-search",
}

_METRIC_TOKEN = re.compile(
    r"\b([a-zA-Z_:][a-zA-Z0-9_:]*(?:_total|_seconds|_bytes|_ready|_healthy|_status|_sum|_max))\b"
)

# Every metric name this change actually registers, gathered by grepping the
# instrumentation modules directly rather than re-typing (and risking
# drifting from) the list by hand.
_INSTRUMENTED_METRIC_FILES = (
    ROOT / "libs/python/emg-telemetry/src/emg_telemetry/http_metrics.py",
    ROOT / "libs/python/emg-telemetry/src/emg_telemetry/metrics.py",
    ROOT / "services/knowledge-graph/src/emg_knowledge_graph_api/mutation_observability.py",
    ROOT / "services/knowledge-graph/src/emg_knowledge_graph_api/search_metrics.py",
    ROOT / "services/audit-projector/src/emg_audit_projector/telemetry.py",
    ROOT / "tools/backup/emit_metrics.py",
)
_METRIC_DECL = re.compile(r'"([a-zA-Z_:][a-zA-Z0-9_:]*)"')


def _load() -> dict[str, object]:
    with ALERTS_PATH.open() as handle:
        return yaml.safe_load(handle)


def _all_rules() -> list[tuple[str, dict[str, object]]]:
    doc = _load()
    out = []
    for group in doc["groups"]:
        for rule in group["rules"]:
            out.append((group["name"], rule))
    return out


def _known_metric_names() -> set[str]:
    names: set[str] = set()
    for path in _INSTRUMENTED_METRIC_FILES:
        text = path.read_text()
        names.update(_METRIC_DECL.findall(text))
    return names


def test_alert_rules_file_is_valid_yaml_with_groups():
    doc = _load()
    assert isinstance(doc["groups"], list)
    assert len(doc["groups"]) > 0
    for group in doc["groups"]:
        assert "name" in group
        assert isinstance(group["rules"], list)
        assert len(group["rules"]) > 0


def test_group_names_are_unique():
    doc = _load()
    names = [group["name"] for group in doc["groups"]]
    assert len(names) == len(set(names))


def test_alert_names_are_unique_across_the_whole_file():
    rules = _all_rules()
    names = [rule["alert"] for _, rule in rules]
    assert len(names) == len(
        set(names)
    ), "duplicate alert name would silently shadow in most rule engines"


@pytest.mark.parametrize(
    "group_name,rule", _all_rules(), ids=lambda v: v if isinstance(v, str) else v.get("alert", "?")
)
def test_every_alert_has_the_required_p0_p1_runbook_linkage_fields(group_name, rule):
    """RC-C RUNBOOK LINKAGE requirement: every alert must carry a severity,
    a human summary, a description with enough context to start
    investigating, and a runbook reference -- checked for every alert, not
    only P0/P1, since P2 alerts in this file are still routed to a human
    (governance review) and should not be exempt from having context."""
    assert "alert" in rule
    assert "expr" in rule and rule["expr"].strip()
    assert "for" in rule
    labels = rule.get("labels", {})
    assert labels.get("severity") in {"P0", "P1", "P2"}, rule["alert"]
    assert "category" in labels
    annotations = rule.get("annotations", {})
    assert annotations.get("summary"), f"{rule['alert']} missing annotations.summary"
    assert annotations.get("description"), f"{rule['alert']} missing annotations.description"
    assert annotations.get("runbook"), f"{rule['alert']} missing annotations.runbook"
    assert annotations["runbook"].startswith("docs/operations/alert-runbook.md#")


@pytest.mark.parametrize(
    "group_name,rule", _all_rules(), ids=lambda v: v if isinstance(v, str) else v.get("alert", "?")
)
def test_expression_has_balanced_parens_and_braces(group_name, rule):
    expr = rule["expr"]
    assert expr.count("(") == expr.count(")"), rule["alert"]
    assert expr.count("{") == expr.count("}"), rule["alert"]


@pytest.mark.parametrize(
    "group_name,rule", _all_rules(), ids=lambda v: v if isinstance(v, str) else v.get("alert", "?")
)
def test_no_tenant_entity_query_principal_or_credential_content_in_expr_or_labels(group_name, rule):
    """Privacy/cardinality/tenant-safety adversarial requirement: alert
    definitions themselves (not just the metrics they read) must never
    reference tenant/entity/query/credential-shaped label names -- these
    alerts aggregate across tenants by construction (see each bucket-A
    group's docstring), and a rule author reintroducing a tenant label here
    would defeat that."""
    haystack = " ".join(
        [rule["expr"], " ".join(f"{k}={v}" for k, v in rule.get("labels", {}).items())]
    ).lower()
    for forbidden in _FORBIDDEN_LABEL_SUBSTRINGS:
        assert forbidden not in haystack, f"{rule['alert']} references forbidden term {forbidden!r}"


@pytest.mark.parametrize(
    "group_name,rule",
    [(g, r) for g, r in _all_rules() if g in _BUCKET_A_GROUPS],
    ids=lambda v: v if isinstance(v, str) else v.get("alert", "?"),
)
def test_bucket_a_alerts_reference_only_metrics_this_repository_actually_emits(group_name, rule):
    """Adversarial requirement: alerts using absent metrics. A bucket-A
    group claims its alerts are implementable NOW against emitted metrics;
    every `_total`/`_seconds`/`_bytes`/`_ready`/`_healthy`/`_status`/`_sum`/
    `_max`-suffixed token in its `expr` must be a metric name this
    repository's instrumentation code actually declares somewhere, or a
    PromQL builtin (`absent`, `up`, `rate`, ... are function names, not
    metric names, and are filtered by the suffix-based token pattern
    itself)."""
    known = _known_metric_names()
    expr = rule["expr"]
    tokens = set(_METRIC_TOKEN.findall(expr))
    unknown = {t for t in tokens if t not in known}
    assert not unknown, f"{rule['alert']} references unknown metric(s): {unknown}"


def test_p0_alerts_all_have_a_for_duration_to_avoid_flapping_on_a_single_scrape():
    for _, rule in _all_rules():
        if rule.get("labels", {}).get("severity") == "P0":
            assert rule.get("for"), f"{rule['alert']} is P0 with no `for:` debounce"


def _github_slugify(heading_text: str) -> str:
    """Reimplements GitHub's Markdown heading-to-anchor slug algorithm
    closely enough for this file's headings (ASCII alertnames only): strip
    non-alphanumeric/hyphen/space characters, lowercase, spaces to hyphens."""
    text = re.sub(r"[^\w\s-]", "", heading_text).strip().lower()
    return re.sub(r"[\s]+", "-", text)


def _runbook_anchors() -> set[str]:
    text = RUNBOOK_PATH.read_text()
    headings = re.findall(r"^##\s+(.+)$", text, flags=re.MULTILINE)
    return {_github_slugify(h) for h in headings}


def test_runbook_document_exists_and_is_nonempty():
    assert RUNBOOK_PATH.exists()
    assert len(RUNBOOK_PATH.read_text()) > 1000


@pytest.mark.parametrize(
    "group_name,rule", _all_rules(), ids=lambda v: v if isinstance(v, str) else v.get("alert", "?")
)
def test_every_alerts_runbook_anchor_resolves_to_a_real_heading(group_name, rule):
    """The strongest form of the RC-C RUNBOOK LINKAGE requirement: not just
    "a runbook field is present" (see the required-fields test above) but
    "the exact anchor it points to exists as a heading in
    docs/operations/alert-runbook.md" -- catches a renamed alert whose
    runbook section wasn't renamed to match, or vice versa."""
    anchors = _runbook_anchors()
    runbook_ref = rule["annotations"]["runbook"]
    anchor = runbook_ref.split("#", 1)[1]
    assert anchor == _github_slugify(rule["alert"]), (
        f"{rule['alert']}: runbook anchor {anchor!r} does not match the alert's own "
        f"slugified name {_github_slugify(rule['alert'])!r}"
    )
    assert anchor in anchors, (
        f"{rule['alert']}: no '## {rule['alert']}' (or equivalent) heading found in "
        f"{RUNBOOK_PATH.relative_to(ROOT)}"
    )


def test_every_runbook_heading_is_referenced_by_at_least_one_alert():
    """The inverse check: a runbook section nobody's alert points to is
    either dead documentation or a sign an alert's runbook field drifted."""
    referenced = {rule["annotations"]["runbook"].split("#", 1)[1] for _, rule in _all_rules()}
    orphaned = _runbook_anchors() - referenced
    assert not orphaned, f"runbook headings with no referencing alert: {orphaned}"
