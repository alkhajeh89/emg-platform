"""Governed-search operational limits/retention metrics (RC-C).

Wires `GraphStore.search_representation_metrics()` -- already implemented
and documented as "low-cardinality operational cardinality/storage
observations" in `emg_persistence.postgres.search_repository` -- into the
Prometheus-format registry. No new persistence-layer code; this only reads
an existing, already-tested method and aggregates its rows.

Cardinality/tenant safety: `search_representation_metrics()` returns one row
per (tenant, revision) search representation, which is exactly the kind of
per-tenant, potentially unbounded data that must never become a metric
label (ADR-042 governed search is explicitly retention- and work-bounded to
prevent this at the data layer; the metric layer must not reintroduce it).
This module aggregates every row into a small, fixed number of gauges
(count, byte total, max node count) with no labels at all, never emitting
one time series per tenant or revision.

Cost control: `search_representation_metrics()` runs an unbounded query
over `entity_search_representations` with no `LIMIT`. Recomputing it on
every `/metrics` scrape (which may be as frequent as every 15s) would add
unbounded, frequent load to the primary PostgreSQL connection pool. This
module throttles recomputation to at most once per
`_MIN_REFRESH_INTERVAL_SECONDS`, mirroring the exact throttling pattern
`emg_audit_projector.worker.AuditProjectorWorker._observe_backlog_if_due`
already uses for its own backlog telemetry.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from emg_telemetry import get_logger
from emg_telemetry.metrics import MetricsRegistry, get_registry

from .config import Settings, get_settings

_log = get_logger("knowledge_graph.search_metrics")

_MIN_REFRESH_INTERVAL_SECONDS = 60.0


def install_search_metrics_collector(
    *,
    settings_factory: Callable[[], Settings] = get_settings,
    registry: MetricsRegistry | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Register a scrape-time collector for search retention/storage gauges.

    Call once from `create_app()`. A no-op (never queries the database) when
    `store_backend` is not `postgres`, matching every other store-backend
    guard already used throughout this service (e.g. `store_health`).
    """
    reg = registry or get_registry()
    representations_total = reg.gauge(
        "kg_search_representations_total",
        "Total retained search representations (all tenants, aggregated).",
    )
    total_bytes = reg.gauge(
        "kg_search_total_bytes",
        "Total PostgreSQL storage bytes used by search documents/terms (all tenants).",
    )
    max_node_count = reg.gauge(
        "kg_search_representation_max_node_count",
        "Largest single search representation's node count (all tenants).",
    )
    last_refresh: list[float] = [float("-inf")]

    def collector() -> None:
        now = monotonic()
        if now - last_refresh[0] < _MIN_REFRESH_INTERVAL_SECONDS:
            return
        settings = settings_factory()
        if settings.store_backend != "postgres":
            return
        from .store import graph_store_dependency

        store = graph_store_dependency(settings)
        get_metrics = getattr(store, "search_representation_metrics", None)
        if get_metrics is None:
            return
        rows = get_metrics()
        representations_total.set(float(len(rows)))
        if rows:
            # total_search_bytes (index 6) is a constant relation-size
            # aggregate repeated on every row by the underlying SQL, not a
            # per-row value -- take it once rather than summing it.
            total_bytes.set(float(rows[0][6]))
            max_node_count.set(float(max(row[2] for row in rows)))
        else:
            total_bytes.set(0.0)
            max_node_count.set(0.0)
        last_refresh[0] = now

    reg.add_collector(collector)
