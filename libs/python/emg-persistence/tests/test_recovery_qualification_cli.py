"""ADR-043 Amendment 1 A11 Stage-50 recovery-qualification CLI wiring tests.

Exercises the actual `validate-recovery-qualification` command dispatch in
`emg_persistence.provisioning.__main__` end to end -- not just the
underlying evidence validators in isolation -- so a regression in how the
expected owner/namespace/phase/target values are threaded from the CLI's
required environment variables into the three A9 evidence gates is caught
even if each validator's own unit tests (test_recovery_fence.py,
test_recovery_evidence.py) still pass individually. `validate_provisioned_databases`
is monkeypatched to a no-op: this test suite proves the evidence-attribution
wiring, not PostgreSQL connectivity (covered elsewhere).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from emg_persistence.provisioning import __main__ as provisioning_main
from emg_persistence.provisioning.recovery_fence import (
    NETWORK_POLICY_NAME,
    PHASE_POD_SELECTOR_LABELS,
    canonicalize_network_policy_spec,
    sha256_hex,
)


def _network_fence_spec() -> dict:
    labels = sorted(PHASE_POD_SELECTOR_LABELS["phase2"])
    return {
        "podSelector": {
            "matchExpressions": [
                {"key": "app.kubernetes.io/name", "operator": "In", "values": labels}
            ]
        },
        "policyTypes": ["Egress"],
        "egress": [
            {
                "to": [{"ipBlock": {"cidr": "10.20.30.5/32"}}],
                "ports": [{"protocol": "TCP", "port": 5432}],
            }
        ],
    }


def _write_network_fence_evidence(
    path: Path, *, owner: str, namespace: str = "emg-production"
) -> Path:
    canonical = canonicalize_network_policy_spec(_network_fence_spec())
    payload = {
        "phase": "phase2",
        "network_policy_name": NETWORK_POLICY_NAME,
        "namespace": namespace,
        "target_environment": "production",
        "policy_spec_canonical": canonical,
        "spec_sha256": sha256_hex(canonical),
        "verified_at": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
        "verified_by": owner,
    }
    file_path = path / "network-fence-evidence.json"
    file_path.write_text(json.dumps(payload), encoding="utf-8")
    return file_path


def _write_session_fence_evidence(path: Path, *, owner: str) -> Path:
    payload = {
        "target_environment": "production",
        "database_host": "10.20.30.5",
        "database_port": "5432",
        "database_name": "emg",
        "verified_by": owner,
        "verified_at": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
        "terminated_count": 0,
        "zero_runtime_sessions": True,
    }
    file_path = path / "session-fence-evidence.json"
    file_path.write_text(json.dumps(payload), encoding="utf-8")
    return file_path


def _write_cni_evidence(path: Path, *, owner: str) -> Path:
    payload = {
        "target_environment": "production",
        "cluster_identifier": "projects/emg/locations/us-central1/clusters/emg-production",
        "qualification_method": "gcloud clusters describe: datapathProvider=ADVANCED_DATAPATH",
        "verified_by": owner,
        "verified_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    }
    file_path = path / "cni-qualification-evidence.json"
    file_path.write_text(json.dumps(payload), encoding="utf-8")
    return file_path


def _base_env(tmp_path: Path, *, owner: str) -> dict[str, str]:
    _write_network_fence_evidence(tmp_path, owner=owner)
    _write_session_fence_evidence(tmp_path, owner=owner)
    _write_cni_evidence(tmp_path, owner=owner)
    return {
        "EMG_AUDIT_MIGRATION_POSTGRES_DSN": "postgresql://unused",
        "EMG_KNOWLEDGE_GRAPH_MIGRATION_POSTGRES_DSN": "postgresql://unused",
        "EMG_IDENTITY_MIGRATION_POSTGRES_DSN": "postgresql://unused",
        "EMG_IDENTITY_RECOVERY_TARGET_ENVIRONMENT": "production",
        "EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_PHASE": "phase2",
        "EMG_IDENTITY_CNI_QUALIFICATION_CLUSTER": (
            "projects/emg/locations/us-central1/clusters/emg-production"
        ),
        "EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_OWNER": owner,
        "EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_NAMESPACE": "emg-production",
        "EMG_IDENTITY_RECOVERY_FENCE_EVIDENCE": str(tmp_path / "network-fence-evidence.json"),
        "EMG_IDENTITY_SESSION_FENCE_EVIDENCE": str(tmp_path / "session-fence-evidence.json"),
        "EMG_IDENTITY_CNI_QUALIFICATION_EVIDENCE": str(
            tmp_path / "cni-qualification-evidence.json"
        ),
    }


def _run_main(monkeypatch: pytest.MonkeyPatch, env: dict[str, str], command: str) -> None:
    monkeypatch.setattr(provisioning_main, "validate_provisioned_databases", lambda *_a: None)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", ["emg-persistence-provisioning", command])
    provisioning_main.main()


def test_matching_owner_across_all_three_evidence_types_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _base_env(tmp_path, owner="recovery-coordinator@example.invalid")
    _run_main(monkeypatch, env, "validate-recovery-qualification")


def test_wrong_owner_on_network_fence_evidence_denies_recovery_qualification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _base_env(tmp_path, owner="recovery-coordinator@example.invalid")
    _write_network_fence_evidence(tmp_path, owner="mallory@example.invalid")
    with pytest.raises(SystemExit, match="Stage-50 recovery qualification denied"):
        _run_main(monkeypatch, env, "validate-recovery-qualification")


def test_mixed_owner_evidence_is_denied_even_if_two_of_three_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement: if there are multiple evidence artifacts in one recovery,
    all that are required to be owned by the same fence owner must match the
    same expected owner. This repository defines no distinct CNI-verifier
    role, so a CNI evidence file attributed to a different actor than the
    network- and session-fence evidence must still deny recovery
    qualification, even though it is otherwise valid."""

    env = _base_env(tmp_path, owner="recovery-coordinator@example.invalid")
    _write_cni_evidence(tmp_path, owner="a-different-actor@example.invalid")
    with pytest.raises(SystemExit, match="Stage-50 recovery qualification denied"):
        _run_main(monkeypatch, env, "validate-recovery-qualification")


def test_wrong_namespace_denies_recovery_qualification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _base_env(tmp_path, owner="recovery-coordinator@example.invalid")
    _write_network_fence_evidence(
        tmp_path, owner="recovery-coordinator@example.invalid", namespace="emg-staging-drill"
    )
    with pytest.raises(SystemExit, match="Stage-50 recovery qualification denied"):
        _run_main(monkeypatch, env, "validate-recovery-qualification")


def test_missing_expected_owner_env_var_fails_before_evidence_is_consulted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _base_env(tmp_path, owner="recovery-coordinator@example.invalid")
    del env["EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_OWNER"]
    with pytest.raises(RuntimeError, match="EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_OWNER"):
        _run_main(monkeypatch, env, "validate-recovery-qualification")


def test_missing_expected_namespace_env_var_fails_before_evidence_is_consulted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _base_env(tmp_path, owner="recovery-coordinator@example.invalid")
    del env["EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_NAMESPACE"]
    with pytest.raises(RuntimeError, match="EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_NAMESPACE"):
        _run_main(monkeypatch, env, "validate-recovery-qualification")


def test_normal_stage50_mode_never_requires_expected_owner_or_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Normal deployment mode (validate-database) must remain completely
    unaffected by this round's remediation -- it never touches recovery
    evidence or the new expected owner/namespace inputs at all."""

    monkeypatch.setattr(provisioning_main, "validate_provisioned_databases", lambda *_a: None)
    for key in (
        "EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_OWNER",
        "EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_NAMESPACE",
        "EMG_IDENTITY_RECOVERY_FENCE_EVIDENCE",
        "EMG_IDENTITY_SESSION_FENCE_EVIDENCE",
        "EMG_IDENTITY_CNI_QUALIFICATION_EVIDENCE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("EMG_AUDIT_MIGRATION_POSTGRES_DSN", "postgresql://unused")
    monkeypatch.setenv("EMG_KNOWLEDGE_GRAPH_MIGRATION_POSTGRES_DSN", "postgresql://unused")
    monkeypatch.setenv("EMG_IDENTITY_MIGRATION_POSTGRES_DSN", "postgresql://unused")
    monkeypatch.setattr(sys, "argv", ["emg-persistence-provisioning", "validate-database"])
    provisioning_main.main()
