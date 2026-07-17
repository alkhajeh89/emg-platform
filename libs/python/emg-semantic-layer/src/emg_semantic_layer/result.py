"""Result model (FEAT-05-4).

`SemanticResult` is the immutable **output** shape a conforming executor returns:
the materialised `SemanticGraph` plus bounded `PageInfo`. This library never
produces a result itself (it executes nothing); the type exists so that every
storage binding returns the *same* storage-independent shape, and so consumers
(Search, GraphRAG, Decision, Presentation) can depend on the shape without
depending on the backend.

Like the other output DTOs in the platform, `SemanticResult`/`PageInfo` are frozen
but freely constructable in Python; a consumer must treat them as executor output
and never hand-fabricate one in place of a real query result.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .graph import SemanticGraph


class PageInfo(BaseModel):
    """Bounded window metadata describing which slice a result represents."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    has_more: bool = False

    @model_validator(mode="after")
    def _validate_counts(self) -> PageInfo:
        if self.returned_count > self.limit:
            raise ValueError("returned_count cannot exceed the page limit")
        return self


class SemanticResult(BaseModel):
    """An immutable query result: the materialised subgraph plus page metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    graph: SemanticGraph
    page: PageInfo

    @model_validator(mode="after")
    def _validate_consistency(self) -> SemanticResult:
        if self.page.returned_count != len(self.graph.nodes):
            raise ValueError("page.returned_count must equal the number of nodes in the graph")
        return self
