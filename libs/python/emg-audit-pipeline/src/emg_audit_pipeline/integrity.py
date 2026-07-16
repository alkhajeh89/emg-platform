"""Hash-chain integrity verification (FEAT-04-1).

`verify_chain` recomputes the whole hash chain over an ordered list of
persisted events and reports whether it is intact. It detects:

- a mutated field in any event (its recomputed `event_hash` no longer matches
  the stored one),
- a broken link (an event whose `prev_hash` does not equal the previous
  event's `event_hash`),
- a sequence gap or reordering (sequence numbers must be strictly increasing).

This is how out-of-band mutation — e.g. a direct database write by a
privileged operator — is *detected*. It is the compensating control for the
honest limitation that append-only enforcement via role grants cannot stop a
PostgreSQL superuser from altering storage.
"""

from __future__ import annotations

from dataclasses import dataclass

from emg_audit_client import AuditEvent

from .hashing import GENESIS_PREV_HASH, recompute_event_hash


@dataclass(frozen=True)
class IntegrityReport:
    """Concrete result of a chain verification (satisfies
    `emg_audit_client.IntegrityResult`)."""

    intact: bool
    checked_count: int
    first_broken_sequence: int | None
    detail: str = ""


def verify_chain(events: list[AuditEvent]) -> IntegrityReport:
    """Verify the hash chain over `events` (assumed ordered by
    `sequence_number`). Returns an `IntegrityReport`; `intact` is True only
    when every event's hash recomputes correctly and every link is sound."""
    prev_hash = GENESIS_PREV_HASH
    prev_sequence: int | None = None

    for event in events:
        if prev_sequence is not None and event.sequence_number <= prev_sequence:
            return IntegrityReport(
                intact=False,
                checked_count=event.sequence_number,
                first_broken_sequence=event.sequence_number,
                detail=(
                    f"sequence not strictly increasing at {event.sequence_number} "
                    f"(previous {prev_sequence})"
                ),
            )

        if event.prev_hash != prev_hash:
            return IntegrityReport(
                intact=False,
                checked_count=event.sequence_number,
                first_broken_sequence=event.sequence_number,
                detail=f"broken chain link at sequence {event.sequence_number}",
            )

        # A stored record whose fields no longer form a valid event (e.g. a
        # schema-violating tamper that bypassed the model) must be reported as
        # an integrity failure, never raised as a 500 (Sprint 6 security-review
        # fix, Priority 4).
        try:
            expected = recompute_event_hash(event)
        except Exception as exc:
            return IntegrityReport(
                intact=False,
                checked_count=event.sequence_number,
                first_broken_sequence=event.sequence_number,
                detail=(
                    f"stored record at sequence {event.sequence_number} could not be "
                    f"re-hashed (schema-violating tamper): {exc}"
                ),
            )
        if expected != event.event_hash:
            return IntegrityReport(
                intact=False,
                checked_count=event.sequence_number,
                first_broken_sequence=event.sequence_number,
                detail=f"hash mismatch at sequence {event.sequence_number} (event mutated)",
            )

        prev_hash = event.event_hash
        prev_sequence = event.sequence_number

    return IntegrityReport(
        intact=True,
        checked_count=len(events),
        first_broken_sequence=None,
        detail="chain intact",
    )
