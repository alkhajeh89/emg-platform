"""State-machine tests (FEAT-05-5): the fixed transition table + helpers."""

from __future__ import annotations

from emg_knowledge_lifecycle import (
    ALL_STATES,
    LIVE_STATES,
    VersionState,
    allowed_transitions,
    is_restore_transition,
    is_valid_transition,
)

S = VersionState

# The full legal transition set (mirrors states.py; pinned here as a golden set).
_LEGAL = {
    (S.PROPOSED, S.ACTIVE),
    (S.PROPOSED, S.RETIRED),
    (S.ACTIVE, S.DEPRECATED),
    (S.ACTIVE, S.SUPERSEDED),
    (S.DEPRECATED, S.SUPERSEDED),
    (S.DEPRECATED, S.RETIRED),
    (S.SUPERSEDED, S.ARCHIVED),
    (S.SUPERSEDED, S.RETIRED),
    (S.RETIRED, S.ARCHIVED),
    (S.ARCHIVED, S.SUPERSEDED),
}


def test_transition_table_is_exactly_the_golden_set() -> None:
    actual = {(a, b) for a in ALL_STATES for b in ALL_STATES if is_valid_transition(a, b)}
    assert actual == _LEGAL


def test_no_self_transitions() -> None:
    for s in ALL_STATES:
        assert not is_valid_transition(s, s)


def test_allowed_transitions_matches_table() -> None:
    for a in ALL_STATES:
        assert allowed_transitions(a) == frozenset(b for (x, b) in _LEGAL if x is a)


def test_restore_transition_detection() -> None:
    assert is_restore_transition(S.ARCHIVED, S.SUPERSEDED)
    assert not is_restore_transition(S.ACTIVE, S.SUPERSEDED)


def test_live_states() -> None:
    assert frozenset({S.PROPOSED, S.ACTIVE, S.DEPRECATED}) == LIVE_STATES


def test_all_states_are_unique_and_complete() -> None:
    assert len(ALL_STATES) == len(set(ALL_STATES)) == 6
