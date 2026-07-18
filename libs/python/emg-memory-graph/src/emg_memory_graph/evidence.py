"""Evidence references (FEAT-05-6).

Every node and every edge in the memory graph must reference at least one piece of
traceable evidence (Deliverable 6). An `EvidenceRef` is an immutable pointer to a
real-world artifact — an email, meeting-minutes doc, PDF, Word doc, SharePoint /
Teams / Jira item, or a manual entry — identified by a stable, source-scoped
`locator`. Evidence ids are content-addressed (deterministic), so the same source
artifact always produces the same evidence id and evidence deduplicates naturally.

Evidence is *never* mutated; correcting evidence means adding a new `EvidenceRef`.
`from_provenance` bridges an ontology `ProvenanceReference` (produced by the
ingestion pipeline) into an `EvidenceRef` so graph assertions can cite the exact
audit/provenance trail the pipeline already recorded.
"""

from __future__ import annotations

from datetime import datetime

from emg_ontology import ProvenanceReference
from pydantic import BaseModel, ConfigDict

from .enums import EvidenceSource
from .ids import evidence_id_for
from .labels import SafeLabel, SafeText
from .metadata import Metadata


class EvidenceRef(BaseModel):
    """An immutable, content-addressed reference to a supporting artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: SafeLabel
    source: EvidenceSource
    # A stable, source-scoped pointer: message-id, document path/URL, Jira key, etc.
    locator: SafeLabel
    source_principal: SafeLabel
    captured_at: datetime
    description: SafeText | None = None
    # Optional linkage to the pipeline's audit/provenance trail.
    event_id: SafeLabel | None = None
    correlation_id: SafeLabel | None = None
    metadata: Metadata = Metadata()

    @classmethod
    def create(
        cls,
        *,
        source: EvidenceSource,
        locator: str,
        source_principal: str,
        captured_at: datetime,
        description: str | None = None,
        event_id: str | None = None,
        correlation_id: str | None = None,
        metadata: Metadata | None = None,
    ) -> EvidenceRef:
        """Build an `EvidenceRef` with a deterministic content-addressed id."""
        return cls(
            evidence_id=evidence_id_for(source.value, locator),
            source=source,
            locator=locator,
            source_principal=source_principal,
            captured_at=captured_at,
            description=description,
            event_id=event_id,
            correlation_id=correlation_id,
            metadata=metadata or Metadata(),
        )

    @classmethod
    def from_provenance(
        cls,
        provenance: ProvenanceReference,
        *,
        source: EvidenceSource,
        locator: str,
        captured_at: datetime,
        description: str | None = None,
    ) -> EvidenceRef:
        """Bridge an ontology `ProvenanceReference` into an `EvidenceRef`,
        preserving its source principal, event id and correlation id."""
        return cls.create(
            source=source,
            locator=locator,
            source_principal=provenance.source_principal,
            captured_at=captured_at,
            description=description,
            event_id=provenance.event_id,
            correlation_id=provenance.correlation_id,
        )
