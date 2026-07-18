"""Deterministic entity resolution (FEAT-05-6, Deliverable 3).

Resolves surface mentions of an entity — "Mohammed Al Mansoori", "Mohd Al
Mansoori", "M. Al Mansoori" — into one logical entity, using *deterministic*
algorithms only (no machine learning). Four strategies, each producing zero or
more **match keys** for a mention:

  * ``EXACT``      — the raw ``(type, label)``.
  * ``NORMALIZED`` — case/whitespace/punctuation/diacritic-folded label.
  * ``ALIAS``      — normalized label after token-level alias substitution
    (e.g. ``mohd`` → ``mohammed``), for configured, precise synonyms.
  * ``RULE``       — configurable structural rules; the shipped rule reduces every
    leading token to its initial (``mohammed al mansoori`` → ``m a mansoori``), so
    initialisms/abbreviations unify without an alias table (opt-in — it trades
    precision for recall).

Mentions that share **any** match key are unified with a near-linear union-find
(O(K·α(K)) over the K generated keys), so resolution avoids the naive O(n²)
pairwise comparison. Everything is a pure function of the inputs and the config.

Extension point: `Resolver` is a `Protocol`; a future ML-assisted resolver can
implement the same `resolve(...)` signature (e.g. adding fuzzy candidate scoring)
without changing callers. This module stays strictly deterministic.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, field_validator

from .enums import MatchType
from .ids import _digest
from .labels import SafeLabel, SafeText
from .limits import MAX_ALIASES


# --- normalization (pure) ----------------------------------------------------
def normalize_label(value: str) -> str:
    """Case/whitespace/punctuation/diacritic-folded canonical form. Deterministic
    and idempotent. Legitimate Unicode letters are preserved (only combining
    marks are stripped)."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    folded = without_marks.casefold()
    tokens = ["".join(ch for ch in tok if ch.isalnum()) for tok in folded.split()]
    return " ".join(t for t in tokens if t)


def _tokens(normalized: str) -> list[str]:
    return [t for t in normalized.split(" ") if t]


class ResolutionConfig(BaseModel):
    """Immutable configuration for a resolution run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategies: frozenset[MatchType] = frozenset(
        {MatchType.EXACT, MatchType.NORMALIZED, MatchType.ALIAS}
    )
    # Token-level alias substitutions, keyed by NORMALIZED surface token.
    aliases: tuple[tuple[SafeLabel, SafeLabel], ...] = ()

    @field_validator("aliases")
    @classmethod
    def _bounded_sorted_aliases(
        cls, value: tuple[tuple[str, str], ...]
    ) -> tuple[tuple[str, str], ...]:
        if len(value) > MAX_ALIASES:
            raise ValueError(f"too many aliases (max {MAX_ALIASES})")
        table: dict[str, str] = {}
        for surface, canonical in value:
            norm = normalize_label(surface)
            if norm in table and table[norm] != canonical:
                raise ValueError(f"conflicting alias for {surface!r}")
            table[norm] = normalize_label(canonical)
        return tuple(sorted(table.items()))

    @property
    def alias_map(self) -> dict[str, str]:
        return dict(self.aliases)


class EntityMention(BaseModel):
    """One surface mention of an entity, awaiting resolution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mention_id: SafeLabel
    entity_type: SafeLabel
    label: SafeText


class ResolvedEntity(BaseModel):
    """A logical entity: one or more mentions unified deterministically."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical_id: SafeLabel
    entity_type: SafeLabel
    canonical_label: SafeText
    member_mention_ids: tuple[SafeLabel, ...]
    match_types: tuple[MatchType, ...]


class ResolutionResult(BaseModel):
    """The deterministic outcome of resolving a set of mentions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entities: tuple[ResolvedEntity, ...]
    # (mention_id, canonical_id) pairs, sorted by mention_id.
    assignments: tuple[tuple[SafeLabel, SafeLabel], ...]

    def canonical_id_for(self, mention_id: str) -> str | None:
        for mid, cid in self.assignments:
            if mid == mention_id:
                return cid
        return None


@runtime_checkable
class Resolver(Protocol):
    """Structural contract for an entity resolver (deterministic today; an
    ML-assisted implementation could satisfy the same interface later)."""

    def resolve(self, mentions: tuple[EntityMention, ...]) -> ResolutionResult: ...


class _UnionFind:
    """Union-find with path compression + union by rank (near-linear)."""

    def __init__(self, items: list[str]) -> None:
        self._parent = {x: x for x in items}
        self._rank = dict.fromkeys(items, 0)

    def find(self, x: str) -> str:
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:  # path compression
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1


def _alias_normalized(label: str, alias_map: Mapping[str, str]) -> str:
    return " ".join(alias_map.get(tok, tok) for tok in _tokens(normalize_label(label)))


def _initials_key(label: str, alias_map: Mapping[str, str]) -> str:
    toks = _alias_normalized(label, alias_map).split(" ")
    toks = [t for t in toks if t]
    if not toks:
        return ""
    return " ".join([t[0] for t in toks[:-1]] + [toks[-1]])


class EntityResolver:
    """Deterministic entity resolver. Construct with a `ResolutionConfig`; call
    `resolve` with mentions to get a stable `ResolutionResult`."""

    def __init__(self, config: ResolutionConfig | None = None) -> None:
        self._config = config or ResolutionConfig()

    @property
    def config(self) -> ResolutionConfig:
        return self._config

    def _match_keys(self, mention: EntityMention) -> list[tuple[MatchType, str]]:
        """Generate (strategy, key) pairs. Each key is namespaced by BOTH the
        strategy and the entity type, so different strategies never collide with
        each other (a mention cannot self-match when its normalized and alias
        forms happen to be identical) — two mentions unify only when they share a
        key under the *same* strategy. Empty label forms yield no key."""
        strat = self._config.strategies
        amap = self._config.alias_map
        forms: list[tuple[MatchType, str]] = []
        if MatchType.EXACT in strat:
            forms.append((MatchType.EXACT, mention.label))
        if MatchType.NORMALIZED in strat:
            forms.append((MatchType.NORMALIZED, normalize_label(mention.label)))
        if MatchType.ALIAS in strat:
            forms.append((MatchType.ALIAS, _alias_normalized(mention.label, amap)))
        if MatchType.RULE in strat:
            forms.append((MatchType.RULE, _initials_key(mention.label, amap)))
        return [
            (mtype, f"{mtype.value}\x1f{mention.entity_type}\x1f{form}")
            for mtype, form in forms
            if form
        ]

    def resolve(self, mentions: tuple[EntityMention, ...]) -> ResolutionResult:
        ordered = sorted(mentions, key=lambda m: m.mention_id)
        uf = _UnionFind([m.mention_id for m in ordered])
        # Map each generated match key to the first mention that produced it, then
        # union subsequent producers into it. Keys are namespaced by strategy so a
        # normalized key never collides with an exact key.
        key_owner: dict[str, str] = {}
        match_types: dict[str, set[MatchType]] = {m.mention_id: set() for m in ordered}
        for mention in ordered:
            for mtype, key in self._match_keys(mention):
                owner = key_owner.get(key)
                if owner is not None:
                    uf.union(owner, mention.mention_id)
                    match_types[mention.mention_id].add(mtype)
                    match_types[owner].add(mtype)
                else:
                    key_owner[key] = mention.mention_id
        # Group mentions by union-find root.
        groups: dict[str, list[EntityMention]] = {}
        for mention in ordered:
            groups.setdefault(uf.find(mention.mention_id), []).append(mention)

        entities: list[ResolvedEntity] = []
        assignments: list[tuple[str, str]] = []
        amap = self._config.alias_map
        for members in groups.values():
            # Deterministic canonical label: the lexicographically smallest
            # alias-normalized label among members (stable, machine-independent).
            rep = min(members, key=lambda m: (_alias_normalized(m.label, amap), m.mention_id))
            canonical_key = f"{rep.entity_type}\x1f{_alias_normalized(rep.label, amap)}"
            canonical_id = f"le-{_digest('entity', canonical_key)}"
            member_ids = tuple(sorted(m.mention_id for m in members))
            mtypes = sorted(
                {mt for m in members for mt in match_types[m.mention_id]}, key=lambda x: x.value
            )
            entities.append(
                ResolvedEntity(
                    canonical_id=canonical_id,
                    entity_type=rep.entity_type,
                    canonical_label=rep.label,
                    member_mention_ids=member_ids,
                    match_types=tuple(mtypes),
                )
            )
            for mid in member_ids:
                assignments.append((mid, canonical_id))

        entities.sort(key=lambda e: e.canonical_id)
        assignments.sort(key=lambda pair: pair[0])
        return ResolutionResult(entities=tuple(entities), assignments=tuple(assignments))
