"""Deterministic entity resolution (Deliverable 3)."""

from __future__ import annotations

import pytest
from emg_memory_graph import (
    EntityMention,
    EntityResolver,
    MatchType,
    ResolutionConfig,
    Resolver,
    normalize_label,
)
from emg_memory_graph.limits import MAX_ALIASES
from pydantic import ValidationError


def _mentions(*pairs: tuple[str, str]) -> tuple[EntityMention, ...]:
    return tuple(
        EntityMention(mention_id=mid, entity_type="person", label=label) for mid, label in pairs
    )


def test_normalize_label() -> None:
    assert normalize_label("  Mohámmed  AL-Mansoori ") == "mohammed almansoori"
    assert normalize_label("M.") == "m"
    assert normalize_label("!!!") == ""


def test_exact_and_normalized_grouping() -> None:
    r = EntityResolver().resolve(_mentions(("a", "Acme Corp"), ("b", "acme corp"), ("c", "Other")))
    assert len({r.canonical_id_for(x) for x in ("a", "b")}) == 1
    assert r.canonical_id_for("c") != r.canonical_id_for("a")


def test_alias_unifies_variants() -> None:
    cfg = ResolutionConfig(aliases=(("mohd", "mohammed"), ("m", "mohammed")))
    r = EntityResolver(cfg).resolve(
        _mentions(
            ("m1", "Mohammed Al Mansoori"),
            ("m2", "Mohd Al Mansoori"),
            ("m3", "M. Al Mansoori"),
            ("m4", "Sara Alkhaja"),
        )
    )
    assert len(r.entities) == 2
    assert len({r.canonical_id_for(x) for x in ("m1", "m2", "m3")}) == 1
    # match_types recorded for the unified group
    unified = next(e for e in r.entities if len(e.member_mention_ids) == 3)
    assert MatchType.ALIAS in unified.match_types
    singleton = next(e for e in r.entities if e.member_mention_ids == ("m4",))
    assert singleton.match_types == ()


def test_rule_initials_unify_without_alias_table() -> None:
    cfg = ResolutionConfig(strategies=frozenset({MatchType.NORMALIZED, MatchType.RULE}))
    r = EntityResolver(cfg).resolve(
        _mentions(
            ("m1", "Mohammed Al Mansoori"), ("m2", "Mohd Al Mansoori"), ("m3", "M Al Mansoori")
        )
    )
    assert len(r.entities) == 1


def test_determinism_regardless_of_input_order() -> None:
    cfg = ResolutionConfig(aliases=(("mohd", "mohammed"),))
    ms = _mentions(("m1", "Mohammed Al Mansoori"), ("m2", "Mohd Al Mansoori"))
    a = EntityResolver(cfg).resolve(ms).model_dump()
    b = EntityResolver(cfg).resolve(tuple(reversed(ms))).model_dump()
    assert a == b


def test_canonical_id_stable_content_addressed() -> None:
    r1 = EntityResolver().resolve(_mentions(("m1", "Acme")))
    r2 = EntityResolver().resolve(_mentions(("zz", "Acme")))
    assert r1.entities[0].canonical_id == r2.entities[0].canonical_id


def test_different_types_not_merged() -> None:
    ms = (
        EntityMention(mention_id="m1", entity_type="person", label="Atlas"),
        EntityMention(mention_id="m2", entity_type="project", label="Atlas"),
    )
    r = EntityResolver().resolve(ms)
    assert len(r.entities) == 2


def test_conflicting_alias_rejected() -> None:
    with pytest.raises(ValidationError):
        ResolutionConfig(aliases=(("m", "mohammed"), ("m", "mahmoud")))


def test_too_many_aliases_rejected() -> None:
    with pytest.raises(ValidationError):
        ResolutionConfig(aliases=tuple((f"a{i}", "x") for i in range(MAX_ALIASES + 1)))


def test_resolver_is_structural_protocol() -> None:
    assert isinstance(EntityResolver(), Resolver)


def test_empty_input() -> None:
    r = EntityResolver().resolve(())
    assert r.entities == ()
    assert r.assignments == ()
    assert r.canonical_id_for("x") is None
