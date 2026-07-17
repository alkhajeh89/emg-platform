"""Retention / archive / restore evaluation tests (FEAT-05-5). Deterministic;
explicit as_of (no wall clock)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from emg_knowledge_lifecycle import (
    DEFAULT_RETENTION_POLICY,
    KnowledgeVersion,
    RetentionPolicy,
    VersionIdentifier,
    VersionMetadata,
    VersionState,
    evaluate_archive,
    evaluate_restore,
    evaluate_retention,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
CLOSE = datetime(2026, 2, 1, tzinfo=timezone.utc)  # effective_to anchor
META = VersionMetadata(created_at=T0, author="svc")


def _v(n: int, state: VersionState, eff_to: datetime | None = CLOSE) -> KnowledgeVersion:
    return KnowledgeVersion(
        identifier=VersionIdentifier(entity_id="ent-a", version=n),
        state=state,
        metadata=META,
        effective_from=T0,
        effective_to=eff_to,
    )


def test_active_is_retained_indefinitely() -> None:
    d = evaluate_retention(_v(1, VersionState.ACTIVE, eff_to=None), T0 + timedelta(days=100000))
    assert d.retain and d.expires_on is None


def test_superseded_retention_window() -> None:
    v = _v(1, VersionState.SUPERSEDED)  # default 365d from CLOSE anchor
    before = CLOSE + timedelta(days=100)
    after = CLOSE + timedelta(days=400)
    assert evaluate_retention(v, before).retain
    assert not evaluate_retention(v, after).retain


def test_retired_retention_window_default_30d() -> None:
    v = _v(1, VersionState.RETIRED)
    assert evaluate_retention(v, CLOSE + timedelta(days=10)).retain
    assert not evaluate_retention(v, CLOSE + timedelta(days=40)).retain


def test_archive_eligibility() -> None:
    v = _v(1, VersionState.SUPERSEDED)  # 365d retention
    # not eligible while retained
    assert not evaluate_archive(v, CLOSE + timedelta(days=100)).eligible
    # eligible once retention expired (archive_after_days default 0)
    assert evaluate_archive(v, CLOSE + timedelta(days=400)).eligible


def test_archive_not_eligible_for_live_states() -> None:
    for state in (VersionState.PROPOSED, VersionState.ACTIVE, VersionState.DEPRECATED):
        v = _v(1, state, eff_to=None)
        assert not evaluate_archive(v, CLOSE + timedelta(days=10000)).eligible


def test_archive_not_eligible_when_already_archived() -> None:
    v = _v(1, VersionState.ARCHIVED)
    d = evaluate_archive(v, CLOSE + timedelta(days=10000))
    assert not d.eligible and "already archived" in d.reason


def test_archive_after_days_delay() -> None:
    policy = RetentionPolicy(retain_superseded_days=10, archive_after_days=30)
    v = _v(1, VersionState.SUPERSEDED)
    # retention expires at CLOSE+10; archive-eligible at CLOSE+40
    assert not evaluate_archive(v, CLOSE + timedelta(days=20), policy).eligible
    assert evaluate_archive(v, CLOSE + timedelta(days=45), policy).eligible


def test_restore_eligibility() -> None:
    v = _v(1, VersionState.ARCHIVED)  # restore window default 3650d
    assert evaluate_restore(v, CLOSE + timedelta(days=100)).eligible
    assert not evaluate_restore(v, CLOSE + timedelta(days=4000)).eligible


def test_restore_only_for_archived() -> None:
    v = _v(1, VersionState.SUPERSEDED)
    d = evaluate_restore(v, CLOSE + timedelta(days=1))
    assert not d.eligible and "only archived" in d.reason


def test_evaluation_is_deterministic() -> None:
    v = _v(1, VersionState.SUPERSEDED)
    at = CLOSE + timedelta(days=200)
    assert evaluate_retention(v, at).model_dump() == evaluate_retention(v, at).model_dump()
    assert evaluate_archive(v, at).model_dump() == evaluate_archive(v, at).model_dump()


def test_indefinite_superseded_never_archives() -> None:
    policy = RetentionPolicy(retain_superseded_days=None)
    v = _v(1, VersionState.SUPERSEDED)
    assert evaluate_retention(v, CLOSE + timedelta(days=100000), policy).retain
    assert not evaluate_archive(v, CLOSE + timedelta(days=100000), policy).eligible


def test_default_policy_is_shared_constant() -> None:
    assert DEFAULT_RETENTION_POLICY.retain_superseded_days == 365


def test_restore_window_anchored_to_effective_end_not_archival() -> None:
    """FIX 5 (documented semantics): the restore window is measured from the
    version's effective-end reference (effective_to if set, else effective_from),
    not from an archival timestamp (which this library does not model)."""
    policy = RetentionPolicy(restore_window_days=100)
    # effective_to = CLOSE, so the restore deadline is CLOSE + 100 days.
    v = _v(1, VersionState.ARCHIVED, eff_to=CLOSE)
    assert evaluate_restore(v, CLOSE + timedelta(days=50), policy).eligible
    assert not evaluate_restore(v, CLOSE + timedelta(days=150), policy).eligible

    # With no effective_to, the anchor falls back to effective_from (T0).
    v2 = _v(1, VersionState.ARCHIVED, eff_to=None)
    assert evaluate_restore(v2, T0 + timedelta(days=50), policy).eligible
    assert not evaluate_restore(v2, T0 + timedelta(days=150), policy).eligible
