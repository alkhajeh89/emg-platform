"""ADR-043 Amendment 1 provider-neutral Approved Recovery Authority contract.

Defines the abstract, provider-neutral ``(generation, authority_revision)``
rotation contract required by ADR-043 Amendment 1 A3/A3.2/A3.2.1, and an
in-memory deterministic test double that satisfies it via a genuine atomic
compare-and-set (mechanism 3a).

A provider is deliberately not selected by Amendment 1 (A3): wiring a
specific qualifying external system (for example Vault KV v2's native
``cas`` write parameter) into :class:`ApprovedRecoveryAuthority` is a
separate, environment-specific integration that this module does not
perform, invent, or fabricate a qualification claim for. This module
supplies only the provider-neutral contract and rotation algorithm plus a
deterministic fixture, so the reconciliation and gate code that depends on
an Approved Recovery Authority can be implemented and adversarially tested
without an external provider being available.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Protocol


class AuthorityRotationConflict(Exception):
    """A rotation's expected predecessor is no longer the authority's current
    revision.

    This is the single linearization-point rejection required by A3
    capability 3 (mechanism 3a, or a qualifying mechanism 3b built from a
    genuine alternative provider-native serialization primitive) -- never a
    post-hoc detection performed after two writes have already both been
    treated as successful.
    """


class AuthorityRollbackDetected(Exception):
    """A candidate ``(generation, authority_revision)`` pair is not the
    authority's own current, highest-ever-observed revision (A3.1
    rollback/replay detection).
    """


@dataclass(frozen=True, slots=True)
class AuthorityPair:
    """The externally governed ``(generation, authority_revision)`` pair (A3.1)."""

    generation: str
    authority_revision: str


class ApprovedRecoveryAuthority(Protocol):
    """Provider-neutral Approved Recovery Authority contract (A3).

    An implementation MUST provide all five A3 capabilities: immutable
    append-only version history, monotonically advancing non-reused version
    identifiers, a single-linearization-point serialized rotation, queryable
    version history, and independent RBAC/audit-governed mutation.
    :meth:`rotate` is the sole linearization point: its return is the only
    proof of an accepted transition, and an implementation MUST make it
    atomic against the authority's own current state at the moment of the
    call -- not a read, an unconditional write, and a subsequent inspection
    of history (A3 capability 3 explicitly disqualifies that procedure).
    """

    def read_current(self) -> AuthorityPair:
        """Return the authority's own current ``(generation, authority_revision)``."""
        ...

    def read_history(self) -> tuple[AuthorityPair, ...]:
        """Return every version ever written, oldest first (A3 capability 4)."""
        ...

    def rotate(self, expected_authority_revision: str, candidate_generation: str) -> AuthorityPair:
        """Atomically accept or reject a transition from ``expected_authority_revision``.

        Raises :class:`AuthorityRotationConflict` -- rather than returning a
        value purporting success -- when ``expected_authority_revision`` is
        no longer the authority's current revision at the moment of this
        call's own atomic decision (A3 capability 3, A3.2 step 5).
        """
        ...


class InMemoryApprovedRecoveryAuthority:
    """Deterministic test double satisfying the full A3 contract via a real
    atomic compare-and-set (mechanism 3a).

    This is a fixture, not a production Approved Recovery Authority: it does
    not persist beyond process memory and provides no independent RBAC/audit
    boundary of its own (capability 5). It exists so that the real
    provider-neutral rotation algorithm and reconciliation code (A3.2,
    ``reconcile_identity_recovery``) can be adversarially tested for the
    same-predecessor dual-writer race without fabricating a claim that any
    specific external provider was integrated. The entire read-compare-write
    decision happens inside one held lock, so there is exactly one
    linearization point -- the opposite of the rejected
    read-then-unconditional-write-then-re-read procedure.
    """

    def __init__(self, *, initial_generation: str | None = None) -> None:
        self._lock = threading.Lock()
        generation = initial_generation or str(uuid.uuid4())
        self._history: list[AuthorityPair] = [
            AuthorityPair(generation=generation, authority_revision="1")
        ]

    def read_current(self) -> AuthorityPair:
        with self._lock:
            return self._history[-1]

    def read_history(self) -> tuple[AuthorityPair, ...]:
        with self._lock:
            return tuple(self._history)

    def rotate(self, expected_authority_revision: str, candidate_generation: str) -> AuthorityPair:
        with self._lock:
            if any(pair.generation == candidate_generation for pair in self._history):
                raise ValueError(
                    "candidate generation has already appeared in the authority's history"
                )
            current = self._history[-1]
            if current.authority_revision != expected_authority_revision:
                raise AuthorityRotationConflict(
                    f"expected predecessor revision {expected_authority_revision!r} is "
                    f"no longer current (current is {current.authority_revision!r})"
                )
            next_revision = str(int(current.authority_revision) + 1)
            new_pair = AuthorityPair(
                generation=candidate_generation, authority_revision=next_revision
            )
            self._history.append(new_pair)
            return new_pair


def detect_rollback_or_replay(history: tuple[AuthorityPair, ...], candidate: AuthorityPair) -> None:
    """A3.1 rollback/replay detection: raise unless ``candidate`` is the
    authority's own highest-ever-observed revision. Comparison is by the
    authority's platform-assigned integer revision sequence, never by
    generation content or wall-clock time (A3.1)."""

    if not history:
        raise AuthorityRollbackDetected("authority history is empty; no current state exists")
    highest = max(int(pair.authority_revision) for pair in history)
    if int(candidate.authority_revision) < highest:
        raise AuthorityRollbackDetected(
            f"authority revision {candidate.authority_revision!r} is lower than the "
            f"highest revision ever recorded ({highest}); rejected as rollback/replay"
        )


def rotate_identity_recovery_generation(
    authority: ApprovedRecoveryAuthority, *, max_attempts: int = 1
) -> AuthorityPair:
    """A3.2: rotate the generation using the authority's own linearization
    point (steps 1-7 of the coordinator algorithm; materialization and
    synchronization proof, steps 9-10, are the caller's responsibility).

    A rejected attempt is treated as a concurrent rotation conflict (step
    6): the coordinator re-reads the now-current state and either resumes a
    fresh attempt (up to ``max_attempts``) or raises to the caller, and never
    retries blindly against the stale expected value that was just rejected.
    """

    attempts = 0
    while True:
        attempts += 1
        current = authority.read_current()
        history = authority.read_history()
        detect_rollback_or_replay(history, current)
        candidate = str(uuid.uuid4())
        while any(pair.generation == candidate for pair in history):  # pragma: no cover
            candidate = str(uuid.uuid4())
        try:
            return authority.rotate(current.authority_revision, candidate)
        except AuthorityRotationConflict:
            if attempts >= max_attempts:
                raise
            continue
