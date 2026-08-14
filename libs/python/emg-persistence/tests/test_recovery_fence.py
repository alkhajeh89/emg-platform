"""ADR-043 Amendment 1 A9.4/A9.6 network-fence evidence contract tests.

Pure Python; no live cluster or PostgreSQL required. Proves the fail-closed
evidence gate: missing, malformed, wrong-phase, wrong-target, wrong-label-set,
fabricated/mismatched hash, unsafe egress content, and stale evidence are all
denied, and only an evidence file whose embedded canonical spec hashes to its
own claimed digest and exactly matches the governed per-phase contract is
accepted. Also proves the live additive-policy-bypass detector against the
exact scenario the round-2 independent review identified (a broad
``app.kubernetes.io/part-of: emg-platform`` selector granting the same
PostgreSQL reachability Identity's phase-scoped policy is supposed to deny).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from emg_persistence.provisioning.recovery_fence import (
    NETWORK_POLICY_NAME,
    PHASE_POD_SELECTOR_LABELS,
    RecoveryFenceEvidenceDenied,
    canonicalize_network_policy_spec,
    detect_additive_identity_bypass,
    policy_selects_any_identity_pod,
    selector_matches_labels,
    sha256_hex,
    validate_db_egress_rules,
    validate_recovery_fence_evidence,
)

_NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)

_VALID_EGRESS: list[dict[str, Any]] = [
    {
        "to": [{"ipBlock": {"cidr": "10.20.30.5/32"}}],
        "ports": [{"protocol": "TCP", "port": 5432}],
    }
]


def _spec_for_phase(phase: str, *, egress: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    labels = sorted(PHASE_POD_SELECTOR_LABELS[phase])
    return {
        "podSelector": {
            "matchExpressions": [
                {"key": "app.kubernetes.io/name", "operator": "In", "values": labels}
            ]
        },
        "policyTypes": ["Egress"],
        "egress": _VALID_EGRESS if egress is None else egress,
    }


def _write(
    path: Path, *, phase: str = "phase2", spec: dict[str, Any] | None = None, **overrides: object
) -> Path:
    # `spec` is always built from a valid phase constant, independent of
    # whatever value ends up in the JSON "phase" field below (a test may
    # deliberately override "phase" to an invalid/empty value via
    # **overrides to prove that case fails closed).
    resolved_spec = (
        spec
        if spec is not None
        else _spec_for_phase(phase if phase in PHASE_POD_SELECTOR_LABELS else "phase2")
    )
    canonical = canonicalize_network_policy_spec(resolved_spec)
    payload: dict[str, object] = {
        "phase": phase,
        "network_policy_name": NETWORK_POLICY_NAME,
        "namespace": "default",
        "target_environment": "production",
        "policy_spec_canonical": canonical,
        "spec_sha256": sha256_hex(canonical),
        "verified_at": (_NOW - timedelta(seconds=30)).isoformat(),
        "verified_by": "recovery-coordinator@example.invalid",
    }
    payload.update(overrides)
    file_path = path / "evidence.json"
    file_path.write_text(json.dumps(payload), encoding="utf-8")
    return file_path


def test_valid_fresh_matching_evidence_is_accepted(tmp_path: Path) -> None:
    path = _write(tmp_path)
    evidence = validate_recovery_fence_evidence(
        path, expected_phase="phase2", expected_target_environment="production", now=_NOW
    )
    assert evidence.phase == "phase2"
    assert evidence.pod_selector_labels == ("emg-identity-recovery-qualify",)


def test_missing_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(RecoveryFenceEvidenceDenied, match="unreadable"):
        validate_recovery_fence_evidence(
            tmp_path / "missing.json",
            expected_phase="phase2",
            expected_target_environment="production",
            now=_NOW,
        )


def test_malformed_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(RecoveryFenceEvidenceDenied, match="malformed"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase2", expected_target_environment="production", now=_NOW
        )


@pytest.mark.parametrize(
    "field",
    [
        "phase",
        "network_policy_name",
        "namespace",
        "target_environment",
        "verified_by",
        "policy_spec_canonical",
        "spec_sha256",
    ],
)
def test_missing_required_field_fails_closed(tmp_path: Path, field: str) -> None:
    path = _write(tmp_path, **{field: ""})
    with pytest.raises(RecoveryFenceEvidenceDenied, match="missing required field"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase2", expected_target_environment="production", now=_NOW
        )


def test_wrong_network_policy_name_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, network_policy_name="some-other-policy")
    with pytest.raises(RecoveryFenceEvidenceDenied, match="wrong NetworkPolicy"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase2", expected_target_environment="production", now=_NOW
        )


def test_wrong_phase_is_rejected(tmp_path: Path) -> None:
    """Phase 1 evidence must never satisfy a Phase 2 gate, and vice versa."""

    path = _write(tmp_path, phase="phase1")
    with pytest.raises(RecoveryFenceEvidenceDenied, match="does not match the required phase"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase2", expected_target_environment="production", now=_NOW
        )


def test_wrong_target_environment_is_rejected(tmp_path: Path) -> None:
    """Evidence captured for staging must never authorize a production fence
    transition (or vice versa) -- target-specific binding (A9.4)."""

    path = _write(tmp_path, target_environment="staging")
    with pytest.raises(RecoveryFenceEvidenceDenied, match="target_environment"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase2", expected_target_environment="production", now=_NOW
        )


# --------------------------------------------------------------------------
# Round-2: hash-binding tests -- a decorative, unverified spec_sha256 was the
# defect independent review found; these prove it is now load-bearing.
# --------------------------------------------------------------------------


def test_fabricated_spec_sha256_is_rejected(tmp_path: Path) -> None:
    """A hand-authored evidence file with a plausible-looking but fabricated
    hash, never actually derived from any real read-back, must fail."""

    path = _write(tmp_path, spec_sha256="ab" * 32)
    with pytest.raises(RecoveryFenceEvidenceDenied, match="does not match"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase2", expected_target_environment="production", now=_NOW
        )


def test_modified_spec_with_stale_hash_is_rejected(tmp_path: Path) -> None:
    """The canonical spec is edited (e.g. to broaden the podSelector back to
    include emg-identity) but the accompanying hash is left as it was for the
    original, narrower spec -- the mismatch must be caught."""

    original_spec = _spec_for_phase("phase2")
    original_canonical = canonicalize_network_policy_spec(original_spec)
    original_hash = sha256_hex(original_canonical)

    tampered_spec = _spec_for_phase("normal")  # a materially different podSelector
    tampered_canonical = canonicalize_network_policy_spec(tampered_spec)

    path = _write(
        tmp_path,
        phase="phase2",
        policy_spec_canonical=tampered_canonical,
        spec_sha256=original_hash,
    )
    with pytest.raises(RecoveryFenceEvidenceDenied, match="does not match"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase2", expected_target_environment="production", now=_NOW
        )


def test_malformed_digest_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, spec_sha256="not-a-hex-digest")
    with pytest.raises(RecoveryFenceEvidenceDenied, match="not a valid SHA-256 digest"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase2", expected_target_environment="production", now=_NOW
        )


def test_short_digest_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, spec_sha256="abc123")
    with pytest.raises(RecoveryFenceEvidenceDenied, match="not a valid SHA-256 digest"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase2", expected_target_environment="production", now=_NOW
        )


def test_non_json_canonical_spec_is_rejected(tmp_path: Path) -> None:
    garbage = "not json"
    path = _write(
        tmp_path,
        policy_spec_canonical=garbage,
        spec_sha256=sha256_hex(garbage),
    )
    with pytest.raises(RecoveryFenceEvidenceDenied, match="not valid JSON"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase2", expected_target_environment="production", now=_NOW
        )


def test_stale_ordinary_workload_label_in_phase2_evidence_is_rejected(tmp_path: Path) -> None:
    """P1 (stale ordinary emg-identity workload) cannot obtain Phase-2 access
    merely by an evidence file whose canonical spec includes its label: the
    label set is re-derived from the hash-bound canonical spec and checked
    against the code-defined governed contract, never trusted as a flat,
    separately-asserted list."""

    spec = _spec_for_phase("phase2")
    spec["podSelector"] = {
        "matchExpressions": [
            {
                "key": "app.kubernetes.io/name",
                "operator": "In",
                "values": ["emg-identity", "emg-identity-recovery-qualify"],
            }
        ]
    }
    path = _write(tmp_path, phase="phase2", spec=spec)
    with pytest.raises(RecoveryFenceEvidenceDenied, match="do not exactly match"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase2", expected_target_environment="production", now=_NOW
        )


def test_partial_label_set_is_rejected(tmp_path: Path) -> None:
    spec = _spec_for_phase("phase1")
    spec["podSelector"] = {
        "matchExpressions": [
            {
                "key": "app.kubernetes.io/name",
                "operator": "In",
                "values": ["emg-identity-migration"],
            }
        ]
    }
    path = _write(tmp_path, phase="phase1", spec=spec)
    with pytest.raises(RecoveryFenceEvidenceDenied, match="do not exactly match"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase1", expected_target_environment="production", now=_NOW
        )


def test_unsafe_default_route_egress_is_rejected(tmp_path: Path) -> None:
    """0.0.0.0/0 is never authorized as a database target by any accepted
    ADR-043 architecture."""

    spec = _spec_for_phase(
        "phase2",
        egress=[
            {
                "to": [{"ipBlock": {"cidr": "0.0.0.0/0"}}],
                "ports": [{"protocol": "TCP", "port": 5432}],
            }
        ],
    )
    path = _write(tmp_path, phase="phase2", spec=spec)
    with pytest.raises(RecoveryFenceEvidenceDenied, match="default route"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase2", expected_target_environment="production", now=_NOW
        )


def test_missing_port_egress_is_rejected(tmp_path: Path) -> None:
    spec = _spec_for_phase("phase2", egress=[{"to": [{"ipBlock": {"cidr": "10.20.30.5/32"}}]}])
    path = _write(tmp_path, phase="phase2", spec=spec)
    with pytest.raises(RecoveryFenceEvidenceDenied, match="no explicit port"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase2", expected_target_environment="production", now=_NOW
        )


def test_placeholder_cidr_is_rejected(tmp_path: Path) -> None:
    """An unresolved template placeholder must never be treated as qualified."""

    spec = _spec_for_phase(
        "phase2",
        egress=[
            {
                "to": [{"ipBlock": {"cidr": "REPLACE_WITH_ENVIRONMENT_POSTGRES_CIDR/32"}}],
                "ports": [{"protocol": "TCP", "port": 5432}],
            }
        ],
    )
    path = _write(tmp_path, phase="phase2", spec=spec)
    with pytest.raises(RecoveryFenceEvidenceDenied, match="invalid or unresolved"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase2", expected_target_environment="production", now=_NOW
        )


def test_empty_egress_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RecoveryFenceEvidenceDenied, match="empty or unresolved"):
        validate_db_egress_rules([])


def test_stale_evidence_beyond_max_age_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, verified_at=(_NOW - timedelta(seconds=2000)).isoformat())
    with pytest.raises(RecoveryFenceEvidenceDenied, match="stale"):
        validate_recovery_fence_evidence(
            path,
            expected_phase="phase2",
            expected_target_environment="production",
            max_age_seconds=900.0,
            now=_NOW,
        )


def test_future_timestamp_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, verified_at=(_NOW + timedelta(seconds=60)).isoformat())
    with pytest.raises(RecoveryFenceEvidenceDenied, match="future"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase2", expected_target_environment="production", now=_NOW
        )


def test_naive_timestamp_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, verified_at="2026-08-14T12:00:00")
    with pytest.raises(RecoveryFenceEvidenceDenied, match="timezone-aware"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase2", expected_target_environment="production", now=_NOW
        )


def test_unknown_expected_phase_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path)
    with pytest.raises(RecoveryFenceEvidenceDenied, match="unknown recovery fence phase"):
        validate_recovery_fence_evidence(
            path, expected_phase="phase3", expected_target_environment="production", now=_NOW
        )


def test_phase_pod_selector_labels_are_pairwise_distinct() -> None:
    """No workload label is ever authorized to reach the DB target under more
    than one phase's governed contract at the same time."""

    normal = set(PHASE_POD_SELECTOR_LABELS["normal"])
    phase1 = set(PHASE_POD_SELECTOR_LABELS["phase1"])
    phase2 = set(PHASE_POD_SELECTOR_LABELS["phase2"])
    assert "emg-identity-recovery-qualify" not in normal | phase1
    assert "emg-identity" not in phase1 | phase2
    assert phase2.isdisjoint(phase1)


# --------------------------------------------------------------------------
# Round-2: live additive-bypass detection tests.
# --------------------------------------------------------------------------


def test_broad_part_of_selector_with_overlapping_egress_is_detected() -> None:
    """Exact reproduction of the round-2 independent review's finding: a
    NetworkPolicy scoped only to app.kubernetes.io/part-of: emg-platform
    (never naming emg-identity directly) that has been filled in with the
    same PostgreSQL CIDR/port Identity's phase-scoped policy protects."""

    bypass_policy = [
        {
            "metadata": {"name": "emg-external-dependencies"},
            "spec": {
                "podSelector": {"matchLabels": {"app.kubernetes.io/part-of": "emg-platform"}},
                "policyTypes": ["Egress"],
                "egress": _VALID_EGRESS,
            },
        }
    ]
    with pytest.raises(RecoveryFenceEvidenceDenied, match="additive policy bypass"):
        detect_additive_identity_bypass(bypass_policy, protected_egress=_VALID_EGRESS)


def test_unrelated_policies_are_not_flagged() -> None:
    """DNS egress and another workload's own db-egress policy (different
    selector, same or different destination) must never trigger a false
    positive."""

    unrelated = [
        {
            "metadata": {"name": "emg-dns-egress"},
            "spec": {
                "podSelector": {"matchLabels": {"app.kubernetes.io/part-of": "emg-platform"}},
                "policyTypes": ["Egress"],
                "egress": [
                    {
                        "to": [
                            {
                                "namespaceSelector": {},
                                "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
                            }
                        ],
                        "ports": [{"protocol": "UDP", "port": 53}],
                    }
                ],
            },
        },
        {
            "metadata": {"name": "emg-audit-db-egress"},
            "spec": {
                "podSelector": {
                    "matchExpressions": [
                        {
                            "key": "app.kubernetes.io/name",
                            "operator": "In",
                            "values": ["emg-audit", "emg-audit-migration"],
                        }
                    ]
                },
                "policyTypes": ["Egress"],
                "egress": _VALID_EGRESS,
            },
        },
    ]
    detect_additive_identity_bypass(unrelated, protected_egress=_VALID_EGRESS)


def test_identity_selecting_policy_to_a_different_destination_is_not_flagged() -> None:
    different_destination = [
        {
            "metadata": {"name": "emg-internal-egress"},
            "spec": {
                "podSelector": {
                    "matchExpressions": [
                        {
                            "key": "app.kubernetes.io/name",
                            "operator": "In",
                            "values": ["emg-identity"],
                        }
                    ]
                },
                "policyTypes": ["Egress"],
                "egress": [
                    {
                        "to": [{"ipBlock": {"cidr": "10.9.9.9/32"}}],
                        "ports": [{"protocol": "TCP", "port": 8000}],
                    }
                ],
            },
        }
    ]
    detect_additive_identity_bypass(different_destination, protected_egress=_VALID_EGRESS)


def test_own_policy_name_is_never_flagged_against_itself() -> None:
    own = [
        {
            "metadata": {"name": NETWORK_POLICY_NAME},
            "spec": {
                "podSelector": {
                    "matchExpressions": [
                        {
                            "key": "app.kubernetes.io/name",
                            "operator": "In",
                            "values": ["emg-identity-recovery-qualify"],
                        }
                    ]
                },
                "policyTypes": ["Egress"],
                "egress": _VALID_EGRESS,
            },
        }
    ]
    detect_additive_identity_bypass(own, protected_egress=_VALID_EGRESS)


def test_selector_matches_labels_empty_selector_matches_everything() -> None:
    assert selector_matches_labels({}, {"app.kubernetes.io/name": "emg-identity"}) is True


def test_policy_selects_any_identity_pod_true_for_part_of_selector() -> None:
    assert (
        policy_selects_any_identity_pod(
            {"podSelector": {"matchLabels": {"app.kubernetes.io/part-of": "emg-platform"}}}
        )
        is True
    )


def test_policy_selects_any_identity_pod_false_for_unrelated_selector() -> None:
    assert (
        policy_selects_any_identity_pod(
            {"podSelector": {"matchLabels": {"app.kubernetes.io/name": "emg-studio"}}}
        )
        is False
    )


# --------------------------------------------------------------------------
# Round-3: A11 fence-owner attribution and namespace-binding tests. Missing
# and blank `verified_by`/`namespace` on the evidence file itself are already
# covered by test_missing_required_field_fails_closed above (both fields are
# in its parametrize list); these tests cover the new expected_owner/
# expected_namespace comparison this round adds.
# --------------------------------------------------------------------------


def test_matching_owner_and_namespace_are_accepted(tmp_path: Path) -> None:
    path = _write(
        tmp_path
    )  # verified_by="recovery-coordinator@example.invalid", namespace="default"
    evidence = validate_recovery_fence_evidence(
        path,
        expected_phase="phase2",
        expected_target_environment="production",
        expected_namespace="default",
        expected_owner="recovery-coordinator@example.invalid",
        now=_NOW,
    )
    assert evidence.verified_by == "recovery-coordinator@example.invalid"
    assert evidence.namespace == "default"


def test_wrong_fence_owner_is_rejected(tmp_path: Path) -> None:
    """Evidence genuinely produced for a different recovery event (a
    different fence owner) must never satisfy this recovery's Stage-50
    gate, even though every other field -- hash, phase, target, freshness --
    is otherwise valid."""

    path = _write(tmp_path, verified_by="mallory@example.invalid")
    with pytest.raises(RecoveryFenceEvidenceDenied, match="A11 attribution check"):
        validate_recovery_fence_evidence(
            path,
            expected_phase="phase2",
            expected_target_environment="production",
            expected_owner="recovery-coordinator@example.invalid",
            now=_NOW,
        )


def test_fence_owner_case_mismatch_is_rejected(tmp_path: Path) -> None:
    """No normalization is defined by the accepted architecture; a
    differently-cased actor string is a different identity, not an alias."""

    path = _write(tmp_path, verified_by="recovery-coordinator@example.invalid")
    with pytest.raises(RecoveryFenceEvidenceDenied, match="A11 attribution check"):
        validate_recovery_fence_evidence(
            path,
            expected_phase="phase2",
            expected_target_environment="production",
            expected_owner="Recovery-Coordinator@example.invalid",
            now=_NOW,
        )


def test_blank_expected_owner_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path)
    with pytest.raises(RecoveryFenceEvidenceDenied, match="expected fence owner must not be blank"):
        validate_recovery_fence_evidence(
            path,
            expected_phase="phase2",
            expected_target_environment="production",
            expected_owner="",
            now=_NOW,
        )


def test_owner_check_is_opt_in_and_does_not_affect_callers_that_omit_it(tmp_path: Path) -> None:
    """The standalone validate-recovery-fence gate (A9.4/A9.6) does not pass
    expected_owner/expected_namespace and must be unaffected by this round's
    remediation."""

    path = _write(tmp_path, verified_by="anyone")
    evidence = validate_recovery_fence_evidence(
        path, expected_phase="phase2", expected_target_environment="production", now=_NOW
    )
    assert evidence.verified_by == "anyone"


def test_wrong_namespace_is_rejected_even_with_matching_environment(tmp_path: Path) -> None:
    """Evidence read back from the wrong namespace within the same target
    environment must not be replayable into this recovery's gate."""

    path = _write(tmp_path, namespace="emg-staging-recovery-drill")
    with pytest.raises(RecoveryFenceEvidenceDenied, match="namespace does not match"):
        validate_recovery_fence_evidence(
            path,
            expected_phase="phase2",
            expected_target_environment="production",
            expected_namespace="emg-production",
            now=_NOW,
        )


def test_blank_expected_namespace_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path)
    with pytest.raises(RecoveryFenceEvidenceDenied, match="expected namespace must not be blank"):
        validate_recovery_fence_evidence(
            path,
            expected_phase="phase2",
            expected_target_environment="production",
            expected_namespace="",
            now=_NOW,
        )
