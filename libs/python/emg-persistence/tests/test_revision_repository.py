"""InMemoryRevisionRepository: first revision, multiple revisions, CAS,
concurrency, retrieval, counting, duplicate protection (Sprint 3).

These verify the repository *contract* deterministically; the PostgreSQL
implementation is exercised by the DB-gated integration tests.
"""

from __future__ import annotations

import threading

import pytest
from _rev_helpers import PRINCIPAL, TENANT, make_revision
from emg_persistence import PersistenceConflictError
from emg_persistence.revisions import (
    InMemoryRevisionRepository,
    RevisionHead,
    RevisionRepository,
)
from emg_platform_core import TenantId


def _repo() -> InMemoryRevisionRepository:
    return InMemoryRevisionRepository()


def test_satisfies_protocol() -> None:
    assert isinstance(_repo(), RevisionRepository)


def test_postgres_repository_construction_and_protocol() -> None:
    # Construction takes an injected connection (no I/O); confirms the PostgreSQL
    # implementation satisfies the same contract. DB behavior is integration-tested.
    from emg_persistence.postgres import PostgresRevisionRepository

    repo = PostgresRevisionRepository(connection=object())  # type: ignore[arg-type]
    assert isinstance(repo, RevisionRepository)


def test_empty_tenant_reads() -> None:
    repo = _repo()
    assert repo.get_head(TENANT) is None
    assert repo.get_revision(TENANT, 1) is None
    assert repo.revision_exists(TENANT, 1) is False
    assert repo.revision_count(TENANT) == 0
    assert repo.tenants() == ()


def test_first_revision() -> None:
    repo = _repo()
    r1 = make_revision(1)
    head = repo.create_first_revision(r1)
    assert head == r1.head()
    assert repo.get_head(TENANT) == r1.head()
    assert repo.get_revision(TENANT, 1) == r1
    assert repo.revision_exists(TENANT, 1) is True
    assert repo.revision_count(TENANT) == 1


def test_first_revision_conflict() -> None:
    repo = _repo()
    repo.create_first_revision(make_revision(1))
    with pytest.raises(PersistenceConflictError):
        repo.create_first_revision(make_revision(1, content_seed="other"))


def test_first_revision_bad_input() -> None:
    repo = _repo()
    with pytest.raises(ValueError):
        repo.create_first_revision(make_revision(2, parent_hash="a" * 64))


def test_multiple_revisions_append_in_order() -> None:
    repo = _repo()
    r1 = make_revision(1)
    repo.create_first_revision(r1)
    r2 = make_revision(2, parent_hash=r1.content_hash)
    head2 = repo.append_revision(r2)
    assert head2 == r2.head()
    r3 = make_revision(3, parent_hash=r2.content_hash)
    repo.append_revision(r3)
    assert repo.revision_count(TENANT) == 3
    assert repo.get_head(TENANT) == r3.head()


def test_append_optimistic_success_and_failure() -> None:
    repo = _repo()
    r1 = make_revision(1)
    repo.create_first_revision(r1)
    # success: parent matches head
    repo.append_revision(make_revision(2, parent_hash=r1.content_hash))
    # failure: stale parent (points at r1, but head is now r2)
    with pytest.raises(PersistenceConflictError):
        repo.append_revision(make_revision(3, content_seed="stale", parent_hash=r1.content_hash))


def test_append_bad_input() -> None:
    repo = _repo()
    with pytest.raises(ValueError):
        repo.append_revision(make_revision(1))  # no parent_hash / number 1


def test_compare_and_set_head_primitive() -> None:
    repo = _repo()
    h1 = RevisionHead(tenant=TENANT, revision_number=1, content_hash="a" * 64)
    # create head from nothing
    assert repo.compare_and_set_head(TENANT, None, h1) is True
    # re-create from nothing fails (head now exists)
    assert repo.compare_and_set_head(TENANT, None, h1) is False
    h2 = RevisionHead(tenant=TENANT, revision_number=2, content_hash="b" * 64)
    # advance from h1 -> h2
    assert repo.compare_and_set_head(TENANT, h1, h2) is True
    # stale expected fails
    assert repo.compare_and_set_head(TENANT, h1, h2) is False


def test_tenant_isolation() -> None:
    repo = _repo()
    other = TenantId.of("other")
    repo.create_first_revision(make_revision(1))
    repo.create_first_revision(make_revision(1, tenant=other, content_seed="o1"))
    assert repo.revision_count(TENANT) == 1
    assert repo.revision_count(other) == 1
    assert repo.get_head(TENANT) != repo.get_head(other)


def test_tenants_returns_sorted_tenants_with_heads() -> None:
    repo = _repo()
    zulu = TenantId.of("zulu")
    alpha = TenantId.of("alpha")
    repo.create_first_revision(make_revision(1, tenant=zulu, content_seed="z1"))
    repo.create_first_revision(make_revision(1, tenant=alpha, content_seed="a1"))
    assert repo.tenants() == (alpha, zulu)


def test_revalidate_head_matches_only_current_authoritative_head() -> None:
    repo = _repo()
    r1 = make_revision(1)
    head1 = repo.create_first_revision(r1)
    assert repo.revalidate_head(TENANT, head1) is True

    r2 = make_revision(2, parent_hash=r1.content_hash)
    repo.append_revision(r2)
    assert repo.revalidate_head(TENANT, head1) is False
    assert repo.revalidate_head(TENANT, r2.head()) is True


def test_revalidate_head_is_false_for_missing_or_different_tenant() -> None:
    repo = _repo()
    head = make_revision(1).head()
    assert repo.revalidate_head(TENANT, head) is False
    assert repo.revalidate_head(TenantId.of("other"), head) is False


def test_concurrent_first_revision_single_winner() -> None:
    repo = _repo()
    n = 16
    barrier = threading.Barrier(n)
    wins: list[bool] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        barrier.wait()
        try:
            repo.create_first_revision(make_revision(1, content_seed=f"w{i}"))
            with lock:
                wins.append(True)
        except PersistenceConflictError:
            pass

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert wins.count(True) == 1
    assert repo.revision_count(TENANT) == 1


def test_concurrent_append_single_winner() -> None:
    repo = _repo()
    r1 = make_revision(1)
    repo.create_first_revision(r1)
    n = 16
    barrier = threading.Barrier(n)
    wins: list[bool] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        barrier.wait()
        try:
            repo.append_revision(
                make_revision(2, content_seed=f"a{i}", parent_hash=r1.content_hash)
            )
            with lock:
                wins.append(True)
        except PersistenceConflictError:
            pass

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert wins.count(True) == 1  # exactly one appended revision 2
    assert repo.revision_count(TENANT) == 2
    assert repo.get_head(TENANT).revision_number == 2  # type: ignore[union-attr]


def test_principal_roundtrip() -> None:
    repo = _repo()
    repo.create_first_revision(make_revision(1))
    stored = repo.get_revision(TENANT, 1)
    assert stored is not None
    assert stored.principal == PRINCIPAL
