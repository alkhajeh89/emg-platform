"""Shared fixtures for the emg-knowledge-pipeline test suite (FEAT-05-2)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from emg_knowledge_pipeline import (
    EntityIngestionRequest,
    IngestionBatch,
    IngestionContext,
    InMemoryGraphStore,
    KnowledgePipeline,
    RelationshipIngestionRequest,
)


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def store() -> InMemoryGraphStore:
    return InMemoryGraphStore()


@pytest.fixture
def pipeline(store: InMemoryGraphStore) -> KnowledgePipeline:
    return KnowledgePipeline(store)


@pytest.fixture
def context() -> IngestionContext:
    return IngestionContext(
        source_principal="emg-svc-ingest",
        source_type="system",
        owner="business-unit-1",
        correlation_id="corr-1",
    )


@pytest.fixture
def person_role_batch(now) -> IngestionBatch:
    return IngestionBatch(
        entities=(
            EntityIngestionRequest(entity_type="Person", natural_key="alice", effective_from=now),
            EntityIngestionRequest(
                entity_type="Role", natural_key="investigator", effective_from=now
            ),
        ),
        relationships=(
            RelationshipIngestionRequest(
                relationship_type="HOLDS",
                from_entity_type="Person",
                from_natural_key="alice",
                to_entity_type="Role",
                to_natural_key="investigator",
                effective_from=now,
            ),
        ),
    )
