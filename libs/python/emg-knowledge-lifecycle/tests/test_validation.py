"""LifecycleValidator tests (FEAT-05-5): typed chain report + transitions."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from emg_knowledge_lifecycle import (
    ChainIssueKind,
    InvalidTransitionError,
    KnowledgeVersion,
    LifecycleEvent,
    LifecyclePolicy,
    LifecycleValidator,
    MissingReasonError,
    VersionChain,
    VersionIdentifier,
    VersionMetadata,
    VersionState,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
MID = datetime(2026, 2, 1, tzinfo=timezone.utc)
META = VersionMetadata(created_at=T0, author="svc")


def _v(entity: str, n: int, state: VersionState, **kw: object) -> KnowledgeVersion:
    return KnowledgeVersion(
        identifier=VersionIdentifier(entity_id=entity, version=n),
        state=state,
        metadata=META,
        effective_from=kw.get("eff_from", T0),  # type: ignore[arg-type]
        effective_to=kw.get("eff_to"),  # type: ignore[arg-type]
        parent=kw.get("parent"),  # type: ignore[arg-type]
    )


def test_valid_chain_report_is_clean() -> None:
    v1 = _v("ent-a", 1, VersionState.SUPERSEDED, eff_from=T0, eff_to=MID)
    v2 = _v("ent-a", 2, VersionState.ACTIVE, parent=v1.identifier, eff_from=MID)
    report = LifecycleValidator.validate_chain((v1, v2))
    assert report.valid
    assert report.issues == ()


def test_report_enumerates_multiple_issues() -> None:
    # Two ACTIVE + mixed entity, built without raising via valid single versions.
    v1 = _v("ent-a", 1, VersionState.ACTIVE, eff_from=T0, eff_to=MID)
    v2 = _v("ent-a", 2, VersionState.ACTIVE, parent=v1.identifier, eff_from=MID)
    v3 = _v("ent-b", 1, VersionState.PROPOSED)
    report = LifecycleValidator.validate_chain((v1, v2, v3))
    assert not report.valid
    kinds = {i.kind for i in report.issues}
    assert ChainIssueKind.DUPLICATE_ACTIVE in kinds
    assert ChainIssueKind.MIXED_ENTITY in kinds


def test_report_detects_orphan() -> None:
    v2 = _v("ent-a", 2, VersionState.ACTIVE, parent=VersionIdentifier(entity_id="ent-a", version=1))
    report = LifecycleValidator.validate_chain((v2,))
    assert ChainIssueKind.ORPHANED_PARENT in {i.kind for i in report.issues}


def test_report_detects_cycle_via_model_construct() -> None:
    a = KnowledgeVersion.model_construct(
        identifier=VersionIdentifier(entity_id="ent-a", version=1),
        state=VersionState.PROPOSED,
        metadata=META,
        parent=VersionIdentifier(entity_id="ent-a", version=2),
        effective_from=T0,
        effective_to=None,
    )
    b = KnowledgeVersion.model_construct(
        identifier=VersionIdentifier(entity_id="ent-a", version=2),
        state=VersionState.PROPOSED,
        metadata=META,
        parent=VersionIdentifier(entity_id="ent-a", version=1),
        effective_from=T0,
        effective_to=None,
    )
    report = LifecycleValidator.validate_chain((a, b))
    assert ChainIssueKind.CYCLE in {i.kind for i in report.issues}
    assert report.issues_of(ChainIssueKind.CYCLE)


def test_report_detects_bad_parent_and_window_via_model_construct() -> None:
    bad = KnowledgeVersion.model_construct(
        identifier=VersionIdentifier(entity_id="ent-a", version=2),
        state=VersionState.ACTIVE,
        metadata=META,
        parent=VersionIdentifier(entity_id="ent-b", version=5),  # cross-entity + non-decreasing
        effective_from=MID,
        effective_to=T0,  # window inverted
    )
    kinds = {i.kind for i in LifecycleValidator.validate_chain((bad,)).issues}
    assert ChainIssueKind.CROSS_ENTITY_PARENT in kinds
    assert ChainIssueKind.NON_DECREASING_PARENT in kinds
    assert ChainIssueKind.INVALID_EFFECTIVE_WINDOW in kinds
    assert ChainIssueKind.ORPHANED_PARENT in kinds


def test_empty_report() -> None:
    report = LifecycleValidator.validate_chain(())
    assert not report.valid
    assert report.issues_of(ChainIssueKind.EMPTY)


def test_assert_valid_chain_builds_chain() -> None:
    v1 = _v("ent-a", 1, VersionState.PROPOSED)
    chain = LifecycleValidator.assert_valid_chain((v1,))
    assert isinstance(chain, VersionChain)


def test_validate_transition_and_assert() -> None:
    assert LifecycleValidator.validate_transition(VersionState.ACTIVE, VersionState.SUPERSEDED)
    assert not LifecycleValidator.validate_transition(VersionState.ACTIVE, VersionState.ARCHIVED)
    LifecycleValidator.assert_transition(VersionState.PROPOSED, VersionState.ACTIVE)  # ok
    with pytest.raises(InvalidTransitionError):
        LifecycleValidator.assert_transition(VersionState.ACTIVE, VersionState.ARCHIVED)


def test_policy_can_disable_restore() -> None:
    no_restore = LifecyclePolicy(allow_restore=False)
    assert not LifecycleValidator.validate_transition(
        VersionState.ARCHIVED, VersionState.SUPERSEDED, no_restore
    )
    with pytest.raises(InvalidTransitionError):
        LifecycleValidator.assert_transition(
            VersionState.ARCHIVED, VersionState.SUPERSEDED, no_restore
        )
    # still legal under the default policy
    assert LifecycleValidator.validate_transition(VersionState.ARCHIVED, VersionState.SUPERSEDED)


# --- FIX 2: require_reason enforcement --------------------------------------

VID = VersionIdentifier(entity_id="ent-a", version=1)


def _event(reason: str | None) -> LifecycleEvent:
    return LifecycleEvent(
        version=VID,
        from_state=VersionState.ACTIVE,
        to_state=VersionState.SUPERSEDED,
        occurred_at=T0,
        actor="svc",
        reason=reason,
    )


def test_require_reason_true_with_reason_ok() -> None:
    strict = LifecyclePolicy(require_reason=True)
    ev = _event("superseded by v2")
    assert LifecycleValidator.validate_event(ev, strict)
    LifecycleValidator.assert_event(ev, strict)  # does not raise


def test_require_reason_true_without_reason_rejected() -> None:
    strict = LifecyclePolicy(require_reason=True)
    ev = _event(None)
    assert not LifecycleValidator.validate_event(ev, strict)
    with pytest.raises(MissingReasonError):
        LifecycleValidator.assert_event(ev, strict)


def test_require_reason_whitespace_only_rejected_at_construction() -> None:
    # A whitespace-only reason cannot be constructed (SafeText rejects it), so the
    # "whitespace reason" case is enforced one layer earlier than require_reason.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _event("   ")


def test_require_reason_false_without_reason_ok() -> None:
    lenient = LifecyclePolicy(require_reason=False)
    ev = _event(None)
    assert LifecycleValidator.validate_event(ev, lenient)
    LifecycleValidator.assert_event(ev, lenient)  # does not raise


def test_assert_event_also_enforces_policy_disabled_transition() -> None:
    no_restore = LifecyclePolicy(allow_restore=False)
    ev = LifecycleEvent(
        version=VID,
        from_state=VersionState.ARCHIVED,
        to_state=VersionState.SUPERSEDED,
        occurred_at=T0,
        actor="svc",
    )
    with pytest.raises(InvalidTransitionError):
        LifecycleValidator.assert_event(ev, no_restore)


def test_validate_event_is_deterministic() -> None:
    strict = LifecyclePolicy(require_reason=True)
    ev = _event(None)
    assert LifecycleValidator.validate_event(ev, strict) == LifecycleValidator.validate_event(
        ev, strict
    )


# --- FIX 3: single O(N) analyzer, reachable INVALID_STATE (no pragma dead code)


def test_invalid_state_reported_via_model_construct() -> None:
    bad = KnowledgeVersion.model_construct(
        identifier=VersionIdentifier(entity_id="ent-a", version=1),
        state="bogus",  # not a VersionState
        metadata=META,
        parent=None,
        effective_from=T0,
        effective_to=None,
    )
    kinds = {i.kind for i in LifecycleValidator.validate_chain((bad,)).issues}
    assert ChainIssueKind.INVALID_STATE in kinds


def test_report_issue_ordering_is_deterministic() -> None:
    v1 = _v("ent-a", 1, VersionState.ACTIVE, eff_from=T0, eff_to=MID)
    v2 = _v("ent-a", 2, VersionState.ACTIVE, parent=v1.identifier, eff_from=MID)
    v3 = _v("ent-b", 1, VersionState.PROPOSED)
    r1 = LifecycleValidator.validate_chain((v1, v2, v3))
    r2 = LifecycleValidator.validate_chain((v1, v2, v3))
    assert [i.model_dump() for i in r1.issues] == [i.model_dump() for i in r2.issues]
