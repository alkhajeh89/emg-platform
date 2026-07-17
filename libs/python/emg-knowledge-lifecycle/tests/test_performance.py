"""Complexity / performance guard for chain validation (FEAT-05-5 review fix).

The independent review found the original chain validation was O(N²) on a deep
legal chain (n=2000 ≈ 1.7s, n=5000 ≈ 10.8s, n=10000 could exceed ~40s). The fix
made it a single O(N) three-colour DFS. These tests build a **deep legal linear
chain at a substantial in-bound size** and assert construction + validation stay
within a **generous, platform-tolerant** wall-clock ceiling that the old O(N²)
implementation would blow through but the O(N) implementation clears with orders
of magnitude to spare.

Chosen size / ceiling (documented):
  * N = 8000 versions (a deep linear chain, well within MAX_CHAIN_SIZE = 10000)
  * CEILING = 5.0s for build + validate combined.
Rationale: the O(N) implementation does this in tens of milliseconds; the old
O(N²) implementation needed ~25-40s for N=8000. A 5s ceiling therefore reliably
fails the quadratic version and passes the linear version on any normal CI host,
without being a flaky microbenchmark.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from emg_knowledge_lifecycle import (
    KnowledgeVersion,
    LifecycleValidator,
    VersionChain,
    VersionIdentifier,
    VersionMetadata,
    VersionState,
)
from emg_knowledge_lifecycle.limits import MAX_CHAIN_SIZE

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
META = VersionMetadata(created_at=T0, author="svc")

_DEEP_N = 8000
_CEILING_SECONDS = 5.0


def _deep_linear_chain(n: int) -> tuple[KnowledgeVersion, ...]:
    """A deep legal linear chain: v1 <- v2 <- ... <- vN, exactly one ACTIVE (vN)."""
    out: list[KnowledgeVersion] = []
    for i in range(1, n + 1):
        parent = VersionIdentifier(entity_id="ent-a", version=i - 1) if i > 1 else None
        state = VersionState.ACTIVE if i == n else VersionState.SUPERSEDED
        out.append(
            KnowledgeVersion(
                identifier=VersionIdentifier(entity_id="ent-a", version=i),
                state=state,
                metadata=META,
                parent=parent,
                effective_from=T0,
                effective_to=None if i == n else T0 + timedelta(days=i),
            )
        )
    return tuple(out)


def test_deep_chain_validation_is_near_linear() -> None:
    assert _DEEP_N < MAX_CHAIN_SIZE
    versions = _deep_linear_chain(_DEEP_N)

    start = time.perf_counter()
    chain = VersionChain(versions=versions)  # constructor delegates to the O(N) analyzer
    report = LifecycleValidator.validate_chain(versions)
    elapsed = time.perf_counter() - start

    assert report.valid
    assert chain.latest().version == _DEEP_N
    assert chain.active() is not None
    # Would fail loudly under the old O(N^2) implementation.
    assert elapsed < _CEILING_SECONDS, f"deep-chain validation took {elapsed:.2f}s"


def test_deep_lineage_walk_is_bounded_and_correct() -> None:
    versions = _deep_linear_chain(_DEEP_N)
    chain = VersionChain(versions=versions)
    start = time.perf_counter()
    lineage = chain.lineage(VersionIdentifier(entity_id="ent-a", version=_DEEP_N))
    elapsed = time.perf_counter() - start
    assert len(lineage) == _DEEP_N  # full ancestry, child -> root
    assert lineage[0].version == _DEEP_N and lineage[-1].version == 1
    assert elapsed < _CEILING_SECONDS


def test_no_recursion_limit_dependence() -> None:
    """The DFS/lineage walks are iterative (a deep chain must not hit Python's
    recursion limit)."""
    import sys

    # A chain far deeper than the default recursion limit must still validate.
    n = min(MAX_CHAIN_SIZE, sys.getrecursionlimit() * 3)
    versions = _deep_linear_chain(n)
    assert LifecycleValidator.validate_chain(versions).valid
    VersionChain(versions=versions)  # must not raise RecursionError
