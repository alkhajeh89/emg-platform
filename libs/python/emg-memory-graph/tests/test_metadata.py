"""Metadata container (FEAT-05-6)."""

from __future__ import annotations

import pytest
from emg_memory_graph import EMPTY_METADATA, Metadata, MetadataItem
from emg_memory_graph.limits import MAX_METADATA_ENTRIES
from pydantic import ValidationError


def test_from_mapping_and_as_dict_roundtrip() -> None:
    m = Metadata.from_mapping({"b": "2", "a": "1"})
    assert m.as_dict() == {"a": "1", "b": "2"}  # sorted by key
    assert m.get("a") == "1"
    assert m.get("missing") is None


def test_empty_metadata() -> None:
    assert EMPTY_METADATA.items == ()
    assert Metadata.from_mapping(None).items == ()
    assert Metadata.from_mapping({}).items == ()


def test_sorted_unique_deterministic() -> None:
    a = Metadata(items=(MetadataItem(key="z", value="1"), MetadataItem(key="a", value="2")))
    b = Metadata(items=(MetadataItem(key="a", value="2"), MetadataItem(key="z", value="1")))
    assert a == b
    assert a.model_dump() == b.model_dump()


def test_conflicting_values_rejected() -> None:
    with pytest.raises(ValidationError):
        Metadata(items=(MetadataItem(key="a", value="1"), MetadataItem(key="a", value="2")))


def test_duplicate_same_value_collapses() -> None:
    m = Metadata(items=(MetadataItem(key="a", value="1"), MetadataItem(key="a", value="1")))
    assert len(m.items) == 1


def test_too_many_entries_rejected() -> None:
    items = tuple(MetadataItem(key=f"k{i}", value="v") for i in range(MAX_METADATA_ENTRIES + 1))
    with pytest.raises(ValidationError):
        Metadata(items=items)


def test_immutable() -> None:
    m = Metadata.from_mapping({"a": "1"})
    with pytest.raises(ValidationError):
        m.items = ()  # type: ignore[misc]
