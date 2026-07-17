"""Observable trust signals (FEAT-05-3).

`TrustSignals` is the **input** to trust scoring and quality-gate validation: a
frozen, bounded record of *observable facts* about a knowledge record — where it
came from, what provenance it carries, how much evidence supports it, whether it
passed validation, and so on.

Critically, there is **no trust field here**. A caller supplies signals; the
engine *computes* the trust score. A caller can therefore never inject or spoof a
trust value — trust is calculated from evidence, deterministically. Signals are
also bounded (non-negative counts, a defined source type, a `[0, 1]`
duplicate-likelihood), so a single manipulated signal cannot push a factor above
its clamp or dominate the composite.

`as_of` is an explicit evaluation timestamp (never a wall clock read inside the
engine), so temporal-freshness decay is reproducible.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The five ingestion source types (mirrors Backlog FEAT-05-2's sources). Defined
# here rather than imported from the ingestion pipeline so trust scoring does not
# depend on it (the pipeline may later depend on trust scoring, not vice versa).
SourceType = Literal["system", "document", "api", "ai", "human"]

LifecycleValue = Literal["proposed", "active", "superseded", "retired"]


class TrustSignals(BaseModel):
    """Observable inputs to trust scoring / quality-gate validation. Frozen and
    `extra="forbid"`; contains no trust value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- evaluation clock (explicit; the engine never reads wall time) ---
    as_of: datetime

    # --- source ---
    source_type: SourceType

    # --- provenance (references into Module 6; see emg-ontology ProvenanceReference) ---
    provenance_present: bool = False
    provenance_has_audit_event: bool = False
    provenance_has_correlation: bool = False
    # Count of resolvable Module-6 links (audit event / provenance record /
    # custody event), 0..3.
    provenance_link_count: int = Field(default=0, ge=0, le=3)

    # --- evidence ---
    evidence_expected: int = Field(default=0, ge=0)
    evidence_present: int = Field(default=0, ge=0)
    evidence_conflicts: int = Field(default=0, ge=0)

    # --- validation status (from ontology conformance + these quality gates) ---
    ontology_conformant: bool = True
    validation_error_count: int = Field(default=0, ge=0)
    validation_warning_count: int = Field(default=0, ge=0)

    # --- ownership ---
    owner_present: bool = False
    owner_registered: bool = False

    # --- identifier ---
    identifier_present: bool = True
    identifier_wellformed: bool = True

    # --- temporal ---
    effective_from: datetime
    effective_to: datetime | None = None

    # --- relationships ---
    relationship_total: int = Field(default=0, ge=0)
    relationship_conflicts: int = Field(default=0, ge=0)

    # --- ingestion quality ---
    ingestion_redactions: int = Field(default=0, ge=0)
    ingestion_bound_violations: int = Field(default=0, ge=0)

    # --- duplicate likelihood (0 = certainly unique, 1 = certainly duplicate) ---
    duplicate_likelihood: float = Field(default=0.0, ge=0.0, le=1.0)

    # --- lifecycle ---
    lifecycle_status: LifecycleValue = "active"
