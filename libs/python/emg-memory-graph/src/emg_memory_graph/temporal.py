"""Temporal memory (FEAT-05-6, Deliverable 4).

Facts are never overwritten. Instead of replacing ``owner = Ahmed`` with
``owner = Mohammed``, the graph keeps an ordered, non-overlapping timeline of
``TemporalFact`` values, each valid over a half-open interval ``[valid_from,
valid_until)`` and each backed by evidence. ``TemporalHistory.as_of(moment)``
reconstructs the value that held at any past instant; ``with_change`` produces a
*new* history that closes the previous open interval and appends the new value,
leaving the prior history intact (immutability).

Valid time is a single non-overlapping timeline per attribute (a deliberate
simplification of full bitemporality — ``recorded_at`` captures transaction time
separately). Overlap or inverted intervals are rejected at construction.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .evidence import EvidenceRef
from .labels import SafeLabel, SafeText
from .limits import MAX_TEMPORAL_INTERVALS
from .metadata import Metadata


class TemporalValidity(BaseModel):
    """A half-open valid-time interval ``[valid_from, valid_until)``. A ``None``
    ``valid_until`` means the interval is still open (currently valid)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    valid_from: datetime
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def _ordered(self) -> TemporalValidity:
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be strictly after valid_from")
        return self

    @property
    def is_open(self) -> bool:
        return self.valid_until is None

    def contains(self, moment: datetime) -> bool:
        """True iff ``valid_from <= moment < valid_until`` (open interval → no upper bound)."""
        if moment < self.valid_from:
            return False
        return self.valid_until is None or moment < self.valid_until

    def overlaps(self, other: TemporalValidity) -> bool:
        """True iff the two half-open intervals share any instant. Intervals
        [a, b) and [c, d) overlap iff a < d and c < b (a None end = +infinity)."""
        a, b = self.valid_from, self.valid_until
        c, d = other.valid_from, other.valid_until
        left = d is None or a < d
        right = b is None or c < b
        return left and right


class TemporalFact(BaseModel):
    """An evidence-backed value that held over one valid-time interval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: SafeText
    validity: TemporalValidity
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    recorded_at: datetime
    metadata: Metadata = Metadata()


class TemporalHistory(BaseModel):
    """An ordered, non-overlapping timeline of one attribute's values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attribute: SafeLabel
    facts: tuple[TemporalFact, ...] = ()

    @model_validator(mode="after")
    def _ordered_non_overlapping(self) -> TemporalHistory:
        if len(self.facts) > MAX_TEMPORAL_INTERVALS:
            raise ValueError(f"too many temporal intervals (max {MAX_TEMPORAL_INTERVALS})")
        ordered = sorted(self.facts, key=lambda f: f.validity.valid_from)
        for earlier, later in zip(ordered, ordered[1:], strict=False):
            if earlier.validity.valid_until is None:
                raise ValueError("only the last interval may be open-ended")
            if earlier.validity.valid_until > later.validity.valid_from:
                raise ValueError("temporal intervals for one attribute must not overlap")
        object.__setattr__(self, "facts", tuple(ordered))
        return self

    def as_of(self, moment: datetime) -> TemporalFact | None:
        """The fact whose interval contains `moment` (historical reconstruction),
        or None if the attribute had no value then. O(n) over a bounded timeline."""
        for fact in self.facts:
            if fact.validity.contains(moment):
                return fact
        return None

    def current(self, now: datetime) -> TemporalFact | None:
        """The value in effect at `now` (alias for `as_of`)."""
        return self.as_of(now)

    def timeline(self) -> tuple[TemporalFact, ...]:
        """All facts in chronological order (already sorted)."""
        return self.facts

    def with_change(
        self,
        *,
        value: str,
        effective_from: datetime,
        evidence: tuple[EvidenceRef, ...],
        recorded_at: datetime,
        metadata: Metadata | None = None,
    ) -> TemporalHistory:
        """Return a NEW history that closes the current open interval at
        `effective_from` and appends `value` as the new open interval. The prior
        history is left untouched (facts are never overwritten)."""
        closed: list[TemporalFact] = []
        for fact in self.facts:
            if fact.validity.is_open:
                closed.append(
                    fact.model_copy(
                        update={
                            "validity": TemporalValidity(
                                valid_from=fact.validity.valid_from,
                                valid_until=effective_from,
                            )
                        }
                    )
                )
            else:
                closed.append(fact)
        new_fact = TemporalFact(
            value=value,
            validity=TemporalValidity(valid_from=effective_from, valid_until=None),
            evidence=evidence,
            recorded_at=recorded_at,
            metadata=metadata or Metadata(),
        )
        return TemporalHistory(attribute=self.attribute, facts=(*closed, new_fact))
