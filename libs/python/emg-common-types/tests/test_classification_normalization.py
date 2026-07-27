"""Tests for the shared `normalize_classification_clearance` helper (ADR-026
final blocker fix).

This is the single, shared validation point every `classification_clearance`
normalization boundary in the platform delegates to (human login and legacy
session normalization in `emg_identity.session`, service-token normalization
in `emg_identity.service_token_validator`, `emg_knowledge_graph_api.authn`,
and `emg_audit_service.authn`) — see each service's own tests for
call-site-level coverage. These tests cover the helper's own contract
directly and exhaustively.
"""

from __future__ import annotations

import pytest
from emg_common_types import Classification, normalize_classification_clearance


@pytest.mark.parametrize("valid_value", ["UNCLASSIFIED", "INTERNAL", "CONFIDENTIAL", "SECRET"])
def test_valid_enum_values_survive_unchanged(valid_value):
    assert normalize_classification_clearance(valid_value) == valid_value


@pytest.mark.parametrize("bogus_value", ["banana", "SUPER_SECRET", "foobar", "unclassified"])
def test_unrecognized_strings_normalize_to_unclassified(bogus_value):
    """Includes a lowercase variant of a real member ("unclassified") —
    matching must be exact, not case-insensitive, since `Classification` is
    itself case-sensitive."""
    assert normalize_classification_clearance(bogus_value) == Classification.UNCLASSIFIED.value


@pytest.mark.parametrize("blank_value", ["", "   ", "\t\n"])
def test_blank_and_whitespace_only_strings_normalize_to_unclassified(blank_value):
    assert normalize_classification_clearance(blank_value) == Classification.UNCLASSIFIED.value


def test_missing_value_normalizes_to_unclassified():
    assert normalize_classification_clearance(None) == Classification.UNCLASSIFIED.value


@pytest.mark.parametrize("non_string_value", [12345, 3.14, True, False, [], {}, object()])
def test_non_string_values_normalize_to_unclassified(non_string_value):
    assert normalize_classification_clearance(non_string_value) == Classification.UNCLASSIFIED.value


def test_surrounding_whitespace_around_a_valid_member_does_not_match():
    """ " INTERNAL " is not itself a Classification member -- it must
    normalize to UNCLASSIFIED rather than being silently stripped and
    matched, since the spec does not call out trimming as a distinct
    behavior."""
    assert normalize_classification_clearance(" INTERNAL ") == Classification.UNCLASSIFIED.value


def test_accepts_a_classification_enum_member_directly():
    """Classification subclasses str, so an already-typed enum member (not
    just its raw string value) must also pass through unchanged."""
    assert normalize_classification_clearance(Classification.SECRET) == Classification.SECRET.value
