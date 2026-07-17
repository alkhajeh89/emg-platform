"""Ingestion context — the server-side authority (FEAT-05-2).

Everything a producer must NOT be trusted to assert is carried here and applied
by the pipeline, not taken from the request:

- `source_principal` — the authenticated caller identity (from the validated
  service token at the eventual HTTP boundary; supplied by the caller of the
  pipeline, never from request content). It is the audit `actor` and the anchor
  of `provenance_reference`.
- `source_type` — which of the five FEAT-05-2 ingestion sources this is
  (system / document / api / ai / human). Recorded on the audit event's
  `source_system`.
- `owner` — the business-unit / accountable owner the pipeline stamps onto every
  entity (server-assigned; ADR-016 ownership registry vocabulary — no new role).
- `trust_score` — the interim trust value assigned to every ingested entity.
  Trust *scoring* is FEAT-05-3; until then the pipeline assigns a conservative,
  source-type-derived default rather than trusting a producer-supplied value.
- `correlation_id` — propagated end-to-end onto every emitted audit event
  (ADR-015).
- `ingest_time` — the server clock for the ingestion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from emg_common_types import CorrelationId, new_correlation_id
from emg_ontology import TRUST_SCORE_MAX, TRUST_SCORE_MIN
from pydantic import BaseModel, ConfigDict, Field

# The five ingestion source types named by Backlog FEAT-05-2.
SourceType = Literal["system", "document", "api", "ai", "human"]

# Interim, conservative trust defaults per source type (FEAT-05-3 will replace
# this with a real composite score). Deliberately below 1.0 and lowest for the
# least-attested sources; documented as a placeholder, not a scoring engine.
_DEFAULT_TRUST_BY_SOURCE: dict[str, float] = {
    "system": 0.7,
    "api": 0.6,
    "document": 0.5,
    "human": 0.5,
    "ai": 0.3,
}


class IngestionContext(BaseModel):
    """Server-side ingestion authority. Constructed by the caller of the
    pipeline (e.g. a future ingestion endpoint) from the authenticated request —
    never from producer content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_principal: str
    source_type: SourceType
    owner: str
    correlation_id: CorrelationId = Field(default_factory=new_correlation_id)
    ingest_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Optional explicit trust override; when None the source-type default is used.
    trust_score: float | None = Field(default=None, ge=TRUST_SCORE_MIN, le=TRUST_SCORE_MAX)

    def assigned_trust_score(self) -> float:
        """The server-assigned trust score for entities ingested under this
        context (interim; FEAT-05-3 supersedes)."""
        if self.trust_score is not None:
            return self.trust_score
        return _DEFAULT_TRUST_BY_SOURCE[self.source_type]
