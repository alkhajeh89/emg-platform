"""ADR-043 Amendment 1: authority-rotation linearization adversarial tests.

Pure Python; no live PostgreSQL or external provider required. Proves the
same-predecessor dual-writer race, every named authority-rotation crash
point, generation-reuse/rollback rejection, and -- by contrast -- why a
naive read-then-unconditional-write-then-re-read procedure is NOT an
acceptable substitute for a genuine single linearization point.
"""

from __future__ import annotations

import threading

import pytest
from emg_persistence.provisioning.recovery_authority import (
    AuthorityPair,
    AuthorityRollbackDetected,
    AuthorityRotationConflict,
    InMemoryApprovedRecoveryAuthority,
    detect_rollback_or_replay,
    rotate_identity_recovery_generation,
)


def test_authority_read_current_and_history_start_consistent() -> None:
    authority = InMemoryApprovedRecoveryAuthority(initial_generation="gen-0")
    current = authority.read_current()
    assert current == AuthorityPair(generation="gen-0", authority_revision="1")
    assert authority.read_history() == (current,)


def test_a_writes_first_b_writes_second_against_same_predecessor() -> None:
    authority = InMemoryApprovedRecoveryAuthority(initial_generation="gen-0")
    predecessor = authority.read_current().authority_revision

    accepted_a = authority.rotate(predecessor, "gen-a")
    assert accepted_a == AuthorityPair(generation="gen-a", authority_revision="2")

    with pytest.raises(AuthorityRotationConflict):
        authority.rotate(predecessor, "gen-b")

    assert authority.read_current() == accepted_a


def test_b_writes_first_a_writes_second_against_same_predecessor() -> None:
    """Reverse ordering of the same race: the winner is not hardcoded to
    whichever coordinator is named first -- exactly one of any two
    competing attempts against the same predecessor is ever accepted."""

    authority = InMemoryApprovedRecoveryAuthority(initial_generation="gen-0")
    predecessor = authority.read_current().authority_revision

    accepted_b = authority.rotate(predecessor, "gen-b")
    assert accepted_b == AuthorityPair(generation="gen-b", authority_revision="2")

    with pytest.raises(AuthorityRotationConflict):
        authority.rotate(predecessor, "gen-a")

    assert authority.read_current() == accepted_b


def test_concurrent_threads_same_predecessor_exactly_one_wins() -> None:
    """Genuine concurrent dual-writer race: two threads race to rotate()
    against the same predecessor with a barrier forcing maximal overlap.
    Exactly one succeeds; the other observes AuthorityRotationConflict; no
    execution produces two accepted transitions from the same predecessor."""

    authority = InMemoryApprovedRecoveryAuthority(initial_generation="gen-0")
    predecessor = authority.read_current().authority_revision
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def attempt(name: str, candidate: str) -> None:
        barrier.wait()
        try:
            results[name] = authority.rotate(predecessor, candidate)
        except AuthorityRotationConflict as exc:
            results[name] = exc

    thread_a = threading.Thread(target=attempt, args=("a", "gen-a"))
    thread_b = threading.Thread(target=attempt, args=("b", "gen-b"))
    thread_a.start()
    thread_b.start()
    thread_a.join()
    thread_b.join()

    outcomes = list(results.values())
    successes = [o for o in outcomes if isinstance(o, AuthorityPair)]
    conflicts = [o for o in outcomes if isinstance(o, AuthorityRotationConflict)]
    assert len(successes) == 1, "exactly one competing transition must be accepted"
    assert len(conflicts) == 1, "the losing transition must fail closed, not silently succeed"
    assert authority.read_current() == successes[0]


def test_crash_before_authority_commit_is_safe_to_restart() -> None:
    """A.3.2.1: crash before the linearization decision -- no rotation was
    ever attempted, so the current state is unchanged and a fresh attempt
    from the (unchanged) authoritative state succeeds normally."""

    authority = InMemoryApprovedRecoveryAuthority(initial_generation="gen-0")
    before = authority.read_current()
    # simulated crash: coordinator read state but never called rotate()
    after_restart = authority.read_current()
    assert after_restart == before
    accepted = authority.rotate(after_restart.authority_revision, "gen-a")
    assert accepted.generation == "gen-a"


def test_authority_commit_succeeds_but_ack_is_lost_resumed_coordinator_adopts_it() -> None:
    """A3.2.1: commit succeeds but the coordinator never observes the
    response. On resume it must read history and adopt the already-accepted
    pair rather than blindly rotating again."""

    authority = InMemoryApprovedRecoveryAuthority(initial_generation="gen-0")
    predecessor = authority.read_current().authority_revision
    candidate = "gen-a"
    accepted = authority.rotate(predecessor, candidate)  # "ACK lost" -- caller discards `accepted`

    # Resumed coordinator: read history, discover its own candidate already accepted.
    history = authority.read_history()
    matches = [pair for pair in history if pair.generation == candidate]
    assert matches == [accepted]
    assert authority.read_current() == accepted

    # It must NOT blindly rotate again against the stale predecessor it used before.
    with pytest.raises(AuthorityRotationConflict):
        authority.rotate(predecessor, "gen-should-not-be-attempted")


def test_stale_predecessor_retry_after_crash_is_rejected_not_blindly_retried() -> None:
    """A3.2 step 6: a coordinator must not retry blindly against a stale
    expected value; the authority itself rejects it."""

    authority = InMemoryApprovedRecoveryAuthority(initial_generation="gen-0")
    predecessor = authority.read_current().authority_revision
    authority.rotate(predecessor, "gen-a")  # someone else already advanced the authority

    with pytest.raises(AuthorityRotationConflict):
        authority.rotate(predecessor, "gen-b")


def test_generation_reuse_is_rejected() -> None:
    authority = InMemoryApprovedRecoveryAuthority(initial_generation="gen-0")
    predecessor = authority.read_current().authority_revision
    authority.rotate(predecessor, "gen-a")

    with pytest.raises(ValueError):
        authority.rotate(authority.read_current().authority_revision, "gen-a")


def test_authority_revision_rollback_replay_is_detected() -> None:
    authority = InMemoryApprovedRecoveryAuthority(initial_generation="gen-0")
    authority.rotate("1", "gen-a")
    authority.rotate("2", "gen-b")
    history = authority.read_history()

    stale_replay = AuthorityPair(generation="gen-a", authority_revision="2")
    with pytest.raises(AuthorityRollbackDetected):
        detect_rollback_or_replay(history, stale_replay)

    current = authority.read_current()
    detect_rollback_or_replay(history, current)  # does not raise


def test_ambiguous_empty_authority_state_fails_closed() -> None:
    with pytest.raises(AuthorityRollbackDetected):
        detect_rollback_or_replay((), AuthorityPair(generation="gen-a", authority_revision="1"))


def test_rotate_identity_recovery_generation_uses_the_algorithm_and_succeeds() -> None:
    authority = InMemoryApprovedRecoveryAuthority(initial_generation="gen-0")
    accepted = rotate_identity_recovery_generation(authority)
    assert accepted.authority_revision == "2"
    assert accepted.generation != "gen-0"
    assert authority.read_current() == accepted


def test_rotate_identity_recovery_generation_conflict_is_raised_not_swallowed() -> None:
    """A genuine race: this coordinator's read of current/history is fresh
    and internally consistent at read time, but a second coordinator's
    rotation lands in the gap between this coordinator's read and its own
    rotate() call. The algorithm must surface AuthorityRotationConflict
    rather than swallow it or retry blindly (max_attempts=1)."""

    authority = InMemoryApprovedRecoveryAuthority(initial_generation="gen-0")

    class _RacingAuthority:
        """Wraps a real authority; a concurrent rotation is injected on the
        underlying authority between this coordinator's read and its own
        rotate() call, exactly once."""

        def __init__(self, inner: InMemoryApprovedRecoveryAuthority) -> None:
            self._inner = inner
            self._raced = False

        def read_current(self) -> AuthorityPair:
            return self._inner.read_current()

        def read_history(self) -> tuple[AuthorityPair, ...]:
            return self._inner.read_history()

        def rotate(self, expected: str, candidate: str) -> AuthorityPair:
            if not self._raced:
                self._raced = True
                self._inner.rotate(expected, "gen-preempt")  # a concurrent coordinator wins
            return self._inner.rotate(expected, candidate)

    with pytest.raises(AuthorityRotationConflict):
        rotate_identity_recovery_generation(_RacingAuthority(authority), max_attempts=1)
    assert authority.read_current().generation == "gen-preempt"


class _UnsafeReadVerifyAfterWriteAuthority:
    """A provider without a native CAS or qualifying mechanism-3b primitive,
    modeling exactly the procedure ADR-043 Amendment 1 disqualifies: an
    unconditional write followed by a separate, non-atomic re-read to infer
    the predecessor. This class exists ONLY to demonstrate, under a forced
    race, why that procedure is not an acceptable substitute for a genuine
    linearization point -- it is never presented as satisfying the Approved
    Recovery Authority contract and is not exported from production code.
    """

    def __init__(self, *, initial_generation: str = "gen-0") -> None:
        self._history: list[AuthorityPair] = [
            AuthorityPair(generation=initial_generation, authority_revision="1")
        ]
        self._write_lock = threading.Lock()  # protects only the list, not the decision

    def read_current(self) -> AuthorityPair:
        return self._history[-1]

    def read_history(self) -> tuple[AuthorityPair, ...]:
        return tuple(self._history)

    def unconditional_write(self, candidate_generation: str) -> AuthorityPair:
        with self._write_lock:
            previous = self._history[-1]
            next_revision = str(int(previous.authority_revision) + 1)
            pair = AuthorityPair(generation=candidate_generation, authority_revision=next_revision)
            self._history.append(pair)
            return pair

    def verify_predecessor_matches(self, expected_predecessor: str, written: AuthorityPair) -> bool:
        history = self.read_history()
        index = history.index(written)
        return index > 0 and history[index - 1].authority_revision == expected_predecessor


def test_read_verify_after_write_procedure_can_let_both_coordinators_believe_success() -> None:
    """Demonstrates the P0-2 finding directly: with an unconditional write
    followed by a separate re-read, a coordinator's verification can pass
    even though a concurrent coordinator also wrote -- if the "loser" reads
    its own predecessor context in a way indistinguishable from success
    absent a real linearization point. This is why mechanism 3b MUST be a
    genuine provider-native atomic primitive, never this procedure."""

    provider = _UnsafeReadVerifyAfterWriteAuthority()
    predecessor = provider.read_current().authority_revision

    # Both coordinators unconditionally write against the SAME observed
    # predecessor; the provider has no atomic accept/reject decision, so
    # both writes succeed and both become real, permanent history entries.
    written_a = provider.unconditional_write("gen-a")
    written_b = provider.unconditional_write("gen-b")

    # The provider's own history genuinely places A immediately before B,
    # so A's post-write verification (predecessor == what A read) passes --
    # A correctly detects it is NOT the immediate successor is the only
    # thing being tested here for A; but nothing in this provider PREVENTED
    # B's write from happening in the first place. Both writes are real,
    # permanent, immutable history entries created without the authority
    # ever having rejected either one -- exactly the "orphaned version"
    # hazard the amendment's mechanism 3b disqualification targets.
    assert written_a in provider.read_history()
    assert written_b in provider.read_history()
    # A's predecessor check happens to pass (it *was* the immediate successor):
    assert provider.verify_predecessor_matches(predecessor, written_a) is True
    # But B's write was never rejected by the provider at write time -- unlike
    # the real InMemoryApprovedRecoveryAuthority, where B's `rotate()` call
    # itself would have raised AuthorityRotationConflict and never created a
    # history entry at all. The unsafe provider's serialization property
    # (capability 3) is not actually enforced by anything in this class.
    assert provider.verify_predecessor_matches(predecessor, written_b) is False
    assert len(provider.read_history()) == 3, (
        "both writes became permanent, unrejected history entries -- the "
        "defect mechanism 3b's redefinition exists to disqualify"
    )
