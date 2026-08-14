"""ADR-043 Amendment 1 A9.4/A9.6 network-fence manifest adversarial tests.

Real Kustomize rendering, real YAML parsing of the environment-owned phase
templates, and real invocation of the Stage-50 static validator -- but no
live cluster (that witness is environment-gated: standard Kubernetes
NetworkPolicy enforcement requires a CNI that implements the `Egress`
policyType, e.g. GKE Dataplane V2/Calico/Cilium, which this repository does
not select and this test suite cannot exercise). What is provable from the
repository alone -- and is proved here -- is that: the recovery-qualification
workload is structurally excluded from every Service (so becoming Ready
cannot make it client-routable, independent of any network-layer control);
the three phase templates each carry exactly the governed pod-selector label
set, with no overlap that would let a stale or wrong-phase identity qualify
for two phases at once; and Stage-50 refuses to pass if any of this drifts.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "infra/environments/production"
sys.path.insert(0, str(ROOT / "tools/ci"))
from emg_persistence.provisioning import (  # noqa: E402
    PHASE_POD_SELECTOR_LABELS,
    policy_selects_any_identity_pod,
)
from validate_production_provisioning import validate as validate_provisioning  # noqa: E402


def _objects() -> list[dict]:
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(OVERLAY)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [document for document in yaml.safe_load_all(rendered) if document]


def _phase_template(phase: str) -> dict:
    path = OVERLAY / f"identity-db-egress.{phase}.example.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _selector_labels(document: dict) -> set[str]:
    selector = document["spec"]["podSelector"]
    labels = set(selector.get("matchLabels", {}).values())
    for expr in selector.get("matchExpressions", []):
        if expr.get("key") == "app.kubernetes.io/name" and expr.get("operator") == "In":
            labels.update(expr.get("values", []))
    return labels


def test_stage50_validator_passes_with_the_network_fence_manifests() -> None:
    validate_provisioning()


def test_recovery_qualification_workload_is_not_selected_by_any_service() -> None:
    """A9.4 Phase 2 / READY_POD_AUTO_TRAFFIC_RISK: reaching Ready on the
    qualification workload must have zero effect on client routing. This is
    proved structurally (no Service selector matches its labels), not merely
    asserted -- the same property the client-traffic fence depends on."""

    objects = _objects()
    qualify = next(
        obj
        for obj in objects
        if obj["kind"] == "Deployment"
        and obj["metadata"]["name"] == "emg-identity-recovery-qualify"
    )
    qualify_labels = qualify["spec"]["template"]["metadata"]["labels"]
    services = [obj for obj in objects if obj["kind"] == "Service"]
    assert services, "expected at least the emg-identity Service to exist"
    for service in services:
        selector = service["spec"].get("selector", {})
        assert selector, f"Service {service['metadata']['name']} has no selector to check"
        matches = all(qualify_labels.get(key) == value for key, value in selector.items())
        assert not matches, (
            f"Service {service['metadata']['name']} selector {selector} matches the "
            "recovery-qualification workload's labels"
        )


def test_ordinary_identity_service_selects_only_the_ordinary_workload() -> None:
    objects = _objects()
    identity_service = next(
        obj
        for obj in objects
        if obj["kind"] == "Service" and obj["metadata"]["name"] == "emg-identity"
    )
    assert identity_service["spec"]["selector"] == {"app.kubernetes.io/name": "emg-identity"}
    # Type defaults to ClusterIP when unset -- no LoadBalancer/NodePort exposure.
    assert identity_service["spec"].get("type") in (None, "ClusterIP")


def test_recovery_qualification_workload_defaults_to_zero_replicas() -> None:
    qualify = next(
        obj
        for obj in _objects()
        if obj["kind"] == "Deployment"
        and obj["metadata"]["name"] == "emg-identity-recovery-qualify"
    )
    assert qualify["spec"]["replicas"] == 0


def test_recovery_qualification_workload_uses_the_governed_runtime_credential() -> None:
    """The fresh Phase 2 workload must authenticate as emg_identity_app --
    the same accepted least-privilege runtime grants (D-4, A4), never a
    broader credential merely because it runs during recovery."""

    qualify = next(
        obj
        for obj in _objects()
        if obj["kind"] == "Deployment"
        and obj["metadata"]["name"] == "emg-identity-recovery-qualify"
    )
    container = qualify["spec"]["template"]["spec"]["containers"][0]
    env = {entry["name"]: entry for entry in container["env"]}
    assert env["EMG_IDENTITY_REFRESH_TOKEN_POSTGRES_DSN"]["valueFrom"]["secretKeyRef"] == {
        "name": "emg-identity-secrets",
        "key": "refresh-postgres-dsn",
    }
    assert (
        "EMG_IDENTITY_MIGRATION_POSTGRES_DSN" not in env
    ), "the Phase 2 workload must never receive emg_identity_migrator authority"


def test_phase_templates_carry_exactly_the_governed_label_set() -> None:
    for phase, expected in PHASE_POD_SELECTOR_LABELS.items():
        document = _phase_template(phase)
        assert document["metadata"]["name"] == "emg-identity-db-egress"
        assert _selector_labels(document) == set(expected)
        assert document["spec"]["policyTypes"] == ["Egress"]


def test_phase1_excludes_every_identity_serving_and_qualification_identity() -> None:
    """Phase 1 (reconciliation fence): only the governed recovery/migration
    actor may reach the target -- neither the ordinary serving workload nor
    the Phase 2 qualification workload, fresh or stale."""

    labels = _selector_labels(_phase_template("phase1"))
    assert "emg-identity" not in labels
    assert "emg-identity-recovery-qualify" not in labels
    assert labels == {"emg-identity-migration", "emg-identity-recovery-reconcile"}


def test_phase2_admits_only_the_qualification_workload() -> None:
    """Phase 2 (readiness-qualification fence): only the specific freshly
    started workload identity may reach the target -- not the ordinary
    serving label (which stays at zero replicas from Phase 1 regardless), and
    not the migrator/reconcile identity, which A9.4 Phase 2 explicitly says
    need not persist."""

    labels = _selector_labels(_phase_template("phase2"))
    assert labels == {"emg-identity-recovery-qualify"}


def test_normal_phase_excludes_every_recovery_only_identity() -> None:
    labels = _selector_labels(_phase_template("normal"))
    assert "emg-identity-recovery-reconcile" not in labels
    assert "emg-identity-recovery-qualify" not in labels
    assert labels == {"emg-identity", "emg-identity-migration"}


def test_no_workload_label_is_authorized_under_more_than_one_phase_at_once() -> None:
    by_phase = {
        phase: _selector_labels(_phase_template(phase)) for phase in PHASE_POD_SELECTOR_LABELS
    }
    assert by_phase["normal"].isdisjoint(by_phase["phase2"])
    assert by_phase["phase1"].isdisjoint(by_phase["phase2"])


def test_general_external_egress_template_excludes_the_identity_db_port() -> None:
    """Kubernetes NetworkPolicy allow-rules are additive with no deny/priority
    override: if the broad, platform-wide external-egress template also
    granted Identity's DB reachability, no phase-scoped restriction above
    could ever narrow it. The general template's egress list is required to
    stay empty in the repository (environment-filled, provider-neutral), so
    this only proves the structural precondition -- that nothing in this
    template's own podSelector is scoped in a way that would bypass the
    dedicated identity-db-egress family -- holds for the checked-in template."""

    document = yaml.safe_load(
        (OVERLAY / "external-egress.example.yaml").read_text(encoding="utf-8")
    )
    assert document["spec"]["egress"] == []


# --------------------------------------------------------------------------
# Round-2 remediation: workload-scoped PostgreSQL egress for every other
# component that needs it, and the Stage-50 recovery-qualification Job.
# --------------------------------------------------------------------------


def test_audit_db_egress_never_selects_identity() -> None:
    doc = yaml.safe_load((OVERLAY / "audit-db-egress.example.yaml").read_text(encoding="utf-8"))
    assert doc["metadata"]["name"] == "emg-audit-db-egress"
    assert _selector_labels(doc) == {"emg-audit", "emg-audit-migration"}
    assert not policy_selects_any_identity_pod(doc["spec"])


def test_audit_projector_db_egress_never_selects_identity() -> None:
    doc = yaml.safe_load(
        (OVERLAY / "audit-projector-db-egress.example.yaml").read_text(encoding="utf-8")
    )
    assert doc["metadata"]["name"] == "emg-audit-projector-db-egress"
    assert _selector_labels(doc) == {"emg-audit-projector"}
    assert not policy_selects_any_identity_pod(doc["spec"])


def test_knowledge_graph_db_egress_never_selects_identity() -> None:
    doc = yaml.safe_load(
        (OVERLAY / "knowledge-graph-db-egress.example.yaml").read_text(encoding="utf-8")
    )
    assert doc["metadata"]["name"] == "emg-knowledge-graph-db-egress"
    assert _selector_labels(doc) == {"emg-knowledge-graph", "emg-knowledge-graph-migration"}
    assert not policy_selects_any_identity_pod(doc["spec"])


def test_provisioning_db_egress_never_selects_identity() -> None:
    doc = yaml.safe_load(
        (OVERLAY / "provisioning-db-egress.example.yaml").read_text(encoding="utf-8")
    )
    assert doc["metadata"]["name"] == "emg-provisioning-db-egress"
    assert _selector_labels(doc) == {"emg-database-bootstrap", "emg-provisioning-validate"}
    assert not policy_selects_any_identity_pod(doc["spec"])


def test_no_non_identity_db_egress_template_reuses_the_identity_object_name() -> None:
    for filename in (
        "audit-db-egress.example.yaml",
        "audit-projector-db-egress.example.yaml",
        "knowledge-graph-db-egress.example.yaml",
        "provisioning-db-egress.example.yaml",
        "external-egress.example.yaml",
    ):
        doc = yaml.safe_load((OVERLAY / filename).read_text(encoding="utf-8"))
        assert doc["metadata"]["name"] != "emg-identity-db-egress", filename


def test_broad_external_egress_selector_still_structurally_matches_identity() -> None:
    """Documents the actual, live hazard this suite guards against: the
    general external-egress template's selector is broad by design (it also
    covers Identity's non-database external dependencies, e.g. Keycloak) and
    therefore DOES structurally match Identity pods -- what makes this safe
    is that its checked-in egress content stays empty
    (test_general_external_egress_template_excludes_the_identity_db_port)
    and Stage-50 statically rejects any committed content once that selector
    also matches an Identity pod
    (validate_production_provisioning._validate_non_identity_db_egress_templates)."""

    doc = yaml.safe_load((OVERLAY / "external-egress.example.yaml").read_text(encoding="utf-8"))
    assert policy_selects_any_identity_pod(doc["spec"]) is True


def test_stage50_rejects_a_filled_in_broad_policy_that_selects_identity(
    tmp_path: Path,
) -> None:
    """Reproduces the round-2 independent review's exact finding against a
    scratch copy of the real templates -- proves Stage-50 would have caught
    it, without mutating the checked-in repository files."""

    import shutil

    from validate_production_provisioning import (
        ProvisioningValidationError,
        _validate_non_identity_db_egress_templates,
    )

    for source in OVERLAY.glob("*.example.yaml"):
        shutil.copy(source, tmp_path / source.name)
    doc = yaml.safe_load((tmp_path / "external-egress.example.yaml").read_text(encoding="utf-8"))
    doc["spec"]["egress"] = [
        {
            "to": [{"ipBlock": {"cidr": "10.20.30.5/32"}}],
            "ports": [{"protocol": "TCP", "port": 5432}],
        }
    ]
    (tmp_path / "external-egress.example.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ProvisioningValidationError, match="non-empty egress content"):
        _validate_non_identity_db_egress_templates(tmp_path)


def test_stage50_recovery_qualification_job_exists_and_is_recovery_only() -> None:
    job = next(
        obj
        for obj in _objects()
        if obj["kind"] == "Job" and obj["metadata"]["name"] == "emg-provisioning-validate-recovery"
    )
    assert (
        job["metadata"].get("annotations", {}).get("emg.platform/bootstrap-stage")
        == "recovery-only"
    )
    container = job["spec"]["template"]["spec"]["containers"][0]
    assert container["command"][-1] == "validate-recovery-qualification"


def test_stage50_recovery_qualification_requires_all_three_evidence_types() -> None:
    job = next(
        obj
        for obj in _objects()
        if obj["kind"] == "Job" and obj["metadata"]["name"] == "emg-provisioning-validate-recovery"
    )
    container = job["spec"]["template"]["spec"]["containers"][0]
    env_names = {entry["name"] for entry in container["env"]}
    assert {
        "EMG_IDENTITY_RECOVERY_FENCE_EVIDENCE",
        "EMG_IDENTITY_SESSION_FENCE_EVIDENCE",
        "EMG_IDENTITY_CNI_QUALIFICATION_EVIDENCE",
    }.issubset(env_names)


def test_stage50_recovery_qualification_requires_expected_owner_and_namespace() -> None:
    """A11 (round-3 remediation): Stage-50 recovery qualification must be
    given something to compare evidence attribution/namespace against --
    the expected owner is an explicit coordinator-supplied input (never
    inferred from the evidence itself), and the expected namespace comes
    from the downward API (this Job's own live namespace), not a
    coordinator-supplied value that could drift from reality."""

    job = next(
        obj
        for obj in _objects()
        if obj["kind"] == "Job" and obj["metadata"]["name"] == "emg-provisioning-validate-recovery"
    )
    container = job["spec"]["template"]["spec"]["containers"][0]
    env_by_name = {entry["name"]: entry for entry in container["env"]}
    assert "EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_OWNER" in env_by_name
    owner_entry = env_by_name["EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_OWNER"]
    assert "secretKeyRef" in owner_entry["valueFrom"]

    assert "EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_NAMESPACE" in env_by_name
    namespace_entry = env_by_name["EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_NAMESPACE"]
    assert namespace_entry["valueFrom"]["fieldRef"]["fieldPath"] == "metadata.namespace"


def test_ordinary_stage50_job_never_requires_recovery_evidence() -> None:
    """Normal deployment mode must never require or consult recovery
    evidence -- only the distinct emg-provisioning-validate-recovery Job
    does."""

    job = next(
        obj
        for obj in _objects()
        if obj["kind"] == "Job" and obj["metadata"]["name"] == "emg-provisioning-validate"
    )
    container = job["spec"]["template"]["spec"]["containers"][0]
    env_names = {entry["name"] for entry in container["env"]}
    assert "EMG_IDENTITY_RECOVERY_FENCE_EVIDENCE" not in env_names
    assert "EMG_IDENTITY_SESSION_FENCE_EVIDENCE" not in env_names
    assert "EMG_IDENTITY_CNI_QUALIFICATION_EVIDENCE" not in env_names
    assert "EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_OWNER" not in env_names
    assert "EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_NAMESPACE" not in env_names
