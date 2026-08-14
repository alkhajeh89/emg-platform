"""ADR-043 Amendment 1 A9.3 database-session-fence and CNI egress-enforcement
qualification evidence contract tests.

Pure Python; no live cluster or PostgreSQL required here (the live
termination flow is exercised separately in
tests/integration/test_identity_p0_1_legacy_security_state.py-adjacent real-
PostgreSQL suites -- see test_identity_session_fence_live.py). Proves both
evidence gates fail closed on missing, malformed, wrong-target, stale, or
future evidence, and that the session-fence precondition rejects every
governed runtime/migration role (never emg_identity_app, never
emg_identity_migrator either) before any connection is attempted.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from emg_persistence.provisioning.database import GOVERNED_DATABASE_ROLES
from emg_persistence.provisioning.recovery_evidence import (
    CniQualificationEvidenceDenied,
    SessionFenceEvidenceDenied,
    terminate_and_prove_identity_app_sessions_excluded,
    validate_cni_egress_qualification_evidence,
    validate_session_fence_evidence,
)

_NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# A9.3 database-session fence
# --------------------------------------------------------------------------


def _write_session_evidence(path: Path, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "target_environment": "production",
        "database_host": "10.20.30.5",
        "database_port": "5432",
        "database_name": "emg",
        "verified_by": "recovery-coordinator@example.invalid",
        "verified_at": (_NOW - timedelta(seconds=30)).isoformat(),
        "terminated_count": 2,
        "zero_runtime_sessions": True,
    }
    payload.update(overrides)
    file_path = path / "session-evidence.json"
    file_path.write_text(json.dumps(payload), encoding="utf-8")
    return file_path


def test_valid_session_fence_evidence_is_accepted(tmp_path: Path) -> None:
    path = _write_session_evidence(tmp_path)
    evidence = validate_session_fence_evidence(
        path, expected_target_environment="production", now=_NOW
    )
    assert evidence.zero_runtime_sessions is True
    assert evidence.terminated_count == 2


def test_missing_session_evidence_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SessionFenceEvidenceDenied, match="unreadable"):
        validate_session_fence_evidence(
            tmp_path / "missing.json", expected_target_environment="production", now=_NOW
        )


def test_malformed_session_evidence_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "session-evidence.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(SessionFenceEvidenceDenied, match="malformed"):
        validate_session_fence_evidence(path, expected_target_environment="production", now=_NOW)


def test_zero_runtime_sessions_false_is_rejected(tmp_path: Path) -> None:
    """Evidence must positively assert success; a False or missing value
    (e.g. a partially-written file from an aborted attempt) fails closed."""

    path = _write_session_evidence(tmp_path, zero_runtime_sessions=False)
    with pytest.raises(SessionFenceEvidenceDenied, match="does not prove"):
        validate_session_fence_evidence(path, expected_target_environment="production", now=_NOW)


def test_missing_zero_runtime_sessions_field_is_rejected(tmp_path: Path) -> None:
    path = _write_session_evidence(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["zero_runtime_sessions"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SessionFenceEvidenceDenied, match="does not prove"):
        validate_session_fence_evidence(path, expected_target_environment="production", now=_NOW)


def test_negative_terminated_count_is_rejected(tmp_path: Path) -> None:
    path = _write_session_evidence(tmp_path, terminated_count=-1)
    with pytest.raises(SessionFenceEvidenceDenied, match="terminated_count"):
        validate_session_fence_evidence(path, expected_target_environment="production", now=_NOW)


def test_wrong_target_environment_is_rejected_for_session_evidence(tmp_path: Path) -> None:
    path = _write_session_evidence(tmp_path, target_environment="staging")
    with pytest.raises(SessionFenceEvidenceDenied, match="target_environment"):
        validate_session_fence_evidence(path, expected_target_environment="production", now=_NOW)


def test_stale_session_evidence_is_rejected(tmp_path: Path) -> None:
    path = _write_session_evidence(
        tmp_path, verified_at=(_NOW - timedelta(seconds=2000)).isoformat()
    )
    with pytest.raises(SessionFenceEvidenceDenied, match="stale"):
        validate_session_fence_evidence(
            path, expected_target_environment="production", max_age_seconds=900.0, now=_NOW
        )


def test_future_session_evidence_is_rejected(tmp_path: Path) -> None:
    path = _write_session_evidence(tmp_path, verified_at=(_NOW + timedelta(seconds=60)).isoformat())
    with pytest.raises(SessionFenceEvidenceDenied, match="future"):
        validate_session_fence_evidence(path, expected_target_environment="production", now=_NOW)


# --------------------------------------------------------------------------
# Round-3: A11 fence-owner attribution tests (session-fence evidence carries
# no Kubernetes namespace -- see the module docstring -- so there is no
# namespace check here). Missing/blank verified_by on the evidence file
# itself is already covered by session-evidence's required-field handling in
# recovery_evidence.py's loader (exercised implicitly by every test above
# that never omits it); these tests cover the new expected_owner comparison.
# --------------------------------------------------------------------------


def test_session_evidence_matching_owner_is_accepted(tmp_path: Path) -> None:
    path = _write_session_evidence(tmp_path)
    evidence = validate_session_fence_evidence(
        path,
        expected_target_environment="production",
        expected_owner="recovery-coordinator@example.invalid",
        now=_NOW,
    )
    assert evidence.verified_by == "recovery-coordinator@example.invalid"


def test_session_evidence_wrong_owner_is_rejected(tmp_path: Path) -> None:
    path = _write_session_evidence(tmp_path, verified_by="mallory@example.invalid")
    with pytest.raises(SessionFenceEvidenceDenied, match="A11 attribution check"):
        validate_session_fence_evidence(
            path,
            expected_target_environment="production",
            expected_owner="recovery-coordinator@example.invalid",
            now=_NOW,
        )


def test_session_evidence_blank_expected_owner_is_rejected(tmp_path: Path) -> None:
    path = _write_session_evidence(tmp_path)
    with pytest.raises(SessionFenceEvidenceDenied, match="expected fence owner must not be blank"):
        validate_session_fence_evidence(
            path, expected_target_environment="production", expected_owner="", now=_NOW
        )


def test_session_evidence_owner_check_is_opt_in(tmp_path: Path) -> None:
    path = _write_session_evidence(tmp_path, verified_by="anyone")
    evidence = validate_session_fence_evidence(
        path, expected_target_environment="production", now=_NOW
    )
    assert evidence.verified_by == "anyone"


@pytest.mark.parametrize("role", sorted(GOVERNED_DATABASE_ROLES))
def test_session_fence_rejects_every_governed_role_dsn(tmp_path: Path, role: str) -> None:
    """Never emg_identity_app (the role being fenced), and never
    emg_identity_migrator either (it lacks the PostgreSQL privilege to
    terminate another role's sessions without violating D-2's NOSUPERUSER/
    no-membership contract) -- nor any of the other five governed roles.
    This precondition is checked before any connection is attempted, so it
    is testable without a live PostgreSQL instance."""

    dsn = f"postgresql://{role}:some-password@localhost:5432/emg"
    with pytest.raises(SessionFenceEvidenceDenied, match="governed database-bootstrap"):
        terminate_and_prove_identity_app_sessions_excluded(
            dsn,
            target_environment="production",
            verified_by="test-actor",
            evidence_output=tmp_path / "evidence.json",
        )
    assert not (tmp_path / "evidence.json").exists()


def test_session_fence_rejects_blank_credential(tmp_path: Path) -> None:
    dsn = "postgresql://emg-database-bootstrap-admin@localhost:5432/emg"
    with pytest.raises(SessionFenceEvidenceDenied, match="must contain a credential"):
        terminate_and_prove_identity_app_sessions_excluded(
            dsn,
            target_environment="production",
            verified_by="test-actor",
            evidence_output=tmp_path / "evidence.json",
        )
    assert not (tmp_path / "evidence.json").exists()


# --------------------------------------------------------------------------
# CNI egress-enforcement qualification contract
# --------------------------------------------------------------------------


def _write_cni_evidence(path: Path, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "target_environment": "production",
        "cluster_identifier": "projects/emg/locations/us-central1/clusters/emg-production",
        "qualification_method": "gcloud clusters describe: datapathProvider=ADVANCED_DATAPATH",
        "verified_by": "recovery-coordinator@example.invalid",
        "verified_at": (_NOW - timedelta(days=1)).isoformat(),
    }
    payload.update(overrides)
    file_path = path / "cni-evidence.json"
    file_path.write_text(json.dumps(payload), encoding="utf-8")
    return file_path


def test_valid_cni_qualification_evidence_is_accepted(tmp_path: Path) -> None:
    path = _write_cni_evidence(tmp_path)
    evidence = validate_cni_egress_qualification_evidence(
        path,
        expected_target_environment="production",
        expected_cluster_identifier="projects/emg/locations/us-central1/clusters/emg-production",
        now=_NOW,
    )
    assert evidence.cluster_identifier.endswith("emg-production")


def test_missing_cni_evidence_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(CniQualificationEvidenceDenied, match="unreadable"):
        validate_cni_egress_qualification_evidence(
            tmp_path / "missing.json",
            expected_target_environment="production",
            expected_cluster_identifier="cluster",
            now=_NOW,
        )


def test_malformed_cni_evidence_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "cni-evidence.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(CniQualificationEvidenceDenied, match="malformed"):
        validate_cni_egress_qualification_evidence(
            path,
            expected_target_environment="production",
            expected_cluster_identifier="cluster",
            now=_NOW,
        )


def test_wrong_target_environment_is_rejected_for_cni_evidence(tmp_path: Path) -> None:
    path = _write_cni_evidence(tmp_path, target_environment="staging")
    with pytest.raises(CniQualificationEvidenceDenied, match="target_environment"):
        validate_cni_egress_qualification_evidence(
            path,
            expected_target_environment="production",
            expected_cluster_identifier="projects/emg/locations/us-central1/clusters/emg-production",
            now=_NOW,
        )


def test_wrong_cluster_identifier_is_rejected(tmp_path: Path) -> None:
    """Evidence qualifying a staging cluster must never authorize a
    production recovery, even if target_environment happens to match."""

    path = _write_cni_evidence(tmp_path, cluster_identifier="some-other-cluster")
    with pytest.raises(CniQualificationEvidenceDenied, match="cluster_identifier"):
        validate_cni_egress_qualification_evidence(
            path,
            expected_target_environment="production",
            expected_cluster_identifier="projects/emg/locations/us-central1/clusters/emg-production",
            now=_NOW,
        )


def test_stale_cni_evidence_beyond_90_days_is_rejected(tmp_path: Path) -> None:
    path = _write_cni_evidence(tmp_path, verified_at=(_NOW - timedelta(days=91)).isoformat())
    with pytest.raises(CniQualificationEvidenceDenied, match="stale"):
        validate_cni_egress_qualification_evidence(
            path,
            expected_target_environment="production",
            expected_cluster_identifier="projects/emg/locations/us-central1/clusters/emg-production",
            now=_NOW,
        )


def test_cni_evidence_within_90_days_is_accepted(tmp_path: Path) -> None:
    path = _write_cni_evidence(tmp_path, verified_at=(_NOW - timedelta(days=89)).isoformat())
    validate_cni_egress_qualification_evidence(
        path,
        expected_target_environment="production",
        expected_cluster_identifier="projects/emg/locations/us-central1/clusters/emg-production",
        now=_NOW,
    )


def test_future_cni_evidence_is_rejected(tmp_path: Path) -> None:
    path = _write_cni_evidence(tmp_path, verified_at=(_NOW + timedelta(seconds=60)).isoformat())
    with pytest.raises(CniQualificationEvidenceDenied, match="future"):
        validate_cni_egress_qualification_evidence(
            path,
            expected_target_environment="production",
            expected_cluster_identifier="projects/emg/locations/us-central1/clusters/emg-production",
            now=_NOW,
        )


# --------------------------------------------------------------------------
# Round-3: A11 fence-owner attribution tests. This repository defines no CNI
# verifier role distinct from the fence owner (the writer script takes the
# same EMG_IDENTITY_RECOVERY_FENCE_ACTOR input as the other two evidence
# types), so CNI qualification evidence is checked against the same expected
# owner as network- and session-fence evidence.
# --------------------------------------------------------------------------


def test_cni_evidence_matching_owner_is_accepted(tmp_path: Path) -> None:
    path = _write_cni_evidence(tmp_path)
    evidence = validate_cni_egress_qualification_evidence(
        path,
        expected_target_environment="production",
        expected_cluster_identifier="projects/emg/locations/us-central1/clusters/emg-production",
        expected_owner="recovery-coordinator@example.invalid",
        now=_NOW,
    )
    assert evidence.verified_by == "recovery-coordinator@example.invalid"


def test_cni_evidence_wrong_owner_is_rejected(tmp_path: Path) -> None:
    path = _write_cni_evidence(tmp_path, verified_by="mallory@example.invalid")
    with pytest.raises(CniQualificationEvidenceDenied, match="A11 attribution check"):
        validate_cni_egress_qualification_evidence(
            path,
            expected_target_environment="production",
            expected_cluster_identifier="projects/emg/locations/us-central1/clusters/emg-production",
            expected_owner="recovery-coordinator@example.invalid",
            now=_NOW,
        )


def test_cni_evidence_blank_expected_owner_is_rejected(tmp_path: Path) -> None:
    path = _write_cni_evidence(tmp_path)
    with pytest.raises(
        CniQualificationEvidenceDenied, match="expected fence owner must not be blank"
    ):
        validate_cni_egress_qualification_evidence(
            path,
            expected_target_environment="production",
            expected_cluster_identifier="projects/emg/locations/us-central1/clusters/emg-production",
            expected_owner="",
            now=_NOW,
        )


def test_cni_evidence_owner_check_is_opt_in(tmp_path: Path) -> None:
    path = _write_cni_evidence(tmp_path, verified_by="anyone")
    validate_cni_egress_qualification_evidence(
        path,
        expected_target_environment="production",
        expected_cluster_identifier="projects/emg/locations/us-central1/clusters/emg-production",
        now=_NOW,
    )
