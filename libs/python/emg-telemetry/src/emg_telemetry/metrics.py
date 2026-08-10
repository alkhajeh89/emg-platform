"""Minimal, dependency-free Prometheus/OpenMetrics-compatible metrics registry.

ADR-015 Section 2 (Metrics): "Every module emits quantitative, aggregable
metrics (counts, rates, durations, distributions) against a shared enterprise
metric taxonomy." This module implements the *emission primitive* only -- it
does not select, deploy, or configure a metrics backend/collector. Choosing
where these metrics are scraped, stored, and queried in production (e.g.
self-hosted Prometheus, a managed Prometheus-compatible service, or another
vendor) is an infrastructure decision outside this library's scope; see
`docs/release/EMG_V1_RELEASE_CANDIDATE_CLOSURE_REVIEW.md` RC-P0-C and
`docs/infrastructure/OBSERVABILITY_INFRASTRUCTURE.md`.

Why hand-rolled instead of the `prometheus_client` PyPI package: EMG pins
every production third-party dependency in a hash-locked
`requirements-production.lock` regenerated deterministically by
`pip-compile --generate-hashes`. Adding a new production dependency requires
running that tool to regenerate the lock; this change does not do so, and
therefore does not add one. The text format produced by `render()` is the
same wire format `prometheus_client` would emit (Prometheus text exposition
format 0.0.4), so any Prometheus-compatible scraper can consume it
unchanged, without this library taking on a new pinned dependency.

Cardinality and tenant safety (mandatory - see RC-C alert catalogue
adversarial review): every label set accepted by `labels=` must come from a
small, fixed, code-controlled vocabulary (an HTTP method, a route template,
a status class, an outcome enum, a failure-class name). Never pass a tenant
ID, entity ID, principal ID, free-text query, or other high-cardinality or
sensitive value as a label or metric name. `MAX_LABEL_VALUES_PER_METRIC`
enforces a hard cap defensively: once a metric's distinct label-value
combinations exceed the cap, additional combinations collapse into a single
``other`` bucket rather than growing without bound.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

MAX_LABEL_VALUES_PER_METRIC = 200
_METRIC_NAME_PATTERN = re.compile(r"\A[a-zA-Z_:][a-zA-Z0-9_:]*\Z")
_LABEL_NAME_PATTERN = re.compile(r"\A[a-zA-Z_][a-zA-Z0-9_]*\Z")


def _validate_metric_name(name: str) -> None:
    if not _METRIC_NAME_PATTERN.match(name):
        raise ValueError(f"invalid metric name: {name!r}")


def _validate_label_names(label_names: tuple[str, ...]) -> None:
    for label_name in label_names:
        if not _LABEL_NAME_PATTERN.match(label_name):
            raise ValueError(f"invalid label name: {label_name!r}")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _render_labels(label_names: tuple[str, ...], values: tuple[str, ...]) -> str:
    if not label_names:
        return ""
    pairs = ",".join(
        f'{name}="{_escape(value)}"' for name, value in zip(label_names, values, strict=True)
    )
    return "{" + pairs + "}"


class _CardinalityGuard:
    """Bounds distinct label-value combinations per metric, per process."""

    def __init__(self, max_values: int) -> None:
        self._max_values = max_values
        self._seen: set[tuple[str, ...]] = set()

    def admit(self, key: tuple[str, ...]) -> tuple[str, ...]:
        if key in self._seen:
            return key
        if len(self._seen) >= self._max_values:
            return ("other",) * len(key)
        self._seen.add(key)
        return key


@dataclass
class Counter:
    name: str
    help_text: str
    label_names: tuple[str, ...] = ()
    _values: dict[tuple[str, ...], float] = field(default_factory=dict)
    _guard: _CardinalityGuard = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        _validate_metric_name(self.name)
        _validate_label_names(self.label_names)
        self._guard = _CardinalityGuard(MAX_LABEL_VALUES_PER_METRIC)

    def inc(self, amount: float = 1.0, *, labels: tuple[str, ...] = ()) -> None:
        if amount < 0:
            raise ValueError("Counter.inc() amount must be non-negative")
        if len(labels) != len(self.label_names):
            raise ValueError(
                f"{self.name}: expected {len(self.label_names)} label values, got {len(labels)}"
            )
        with self._lock:
            key = self._guard.admit(labels)
            self._values[key] = self._values.get(key, 0.0) + amount

    def samples(self) -> tuple[tuple[tuple[str, ...], float], ...]:
        with self._lock:
            return tuple(self._values.items())


@dataclass
class Gauge:
    name: str
    help_text: str
    label_names: tuple[str, ...] = ()
    _values: dict[tuple[str, ...], float] = field(default_factory=dict)
    _guard: _CardinalityGuard = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        _validate_metric_name(self.name)
        _validate_label_names(self.label_names)
        self._guard = _CardinalityGuard(MAX_LABEL_VALUES_PER_METRIC)

    def set(self, value: float, *, labels: tuple[str, ...] = ()) -> None:
        if len(labels) != len(self.label_names):
            raise ValueError(
                f"{self.name}: expected {len(self.label_names)} label values, got {len(labels)}"
            )
        with self._lock:
            key = self._guard.admit(labels)
            self._values[key] = value

    def samples(self) -> tuple[tuple[tuple[str, ...], float], ...]:
        with self._lock:
            return tuple(self._values.items())


DEFAULT_LATENCY_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1,
    2.5,
    5,
    10,
)


@dataclass
class Histogram:
    name: str
    help_text: str
    label_names: tuple[str, ...] = ()
    buckets: tuple[float, ...] = DEFAULT_LATENCY_BUCKETS
    _bucket_counts: dict[tuple[str, ...], list[float]] = field(default_factory=dict)
    _sums: dict[tuple[str, ...], float] = field(default_factory=dict)
    _counts: dict[tuple[str, ...], float] = field(default_factory=dict)
    _guard: _CardinalityGuard = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        _validate_metric_name(self.name)
        _validate_label_names(self.label_names)
        if list(self.buckets) != sorted(self.buckets):
            raise ValueError(f"{self.name}: buckets must be strictly increasing")
        self._guard = _CardinalityGuard(MAX_LABEL_VALUES_PER_METRIC)

    def observe(self, value: float, *, labels: tuple[str, ...] = ()) -> None:
        if len(labels) != len(self.label_names):
            raise ValueError(
                f"{self.name}: expected {len(self.label_names)} label values, got {len(labels)}"
            )
        with self._lock:
            key = self._guard.admit(labels)
            counts = self._bucket_counts.setdefault(key, [0.0] * len(self.buckets))
            for index, bound in enumerate(self.buckets):
                if value <= bound:
                    counts[index] += 1
            self._sums[key] = self._sums.get(key, 0.0) + value
            self._counts[key] = self._counts.get(key, 0.0) + 1

    def samples(
        self,
    ) -> tuple[tuple[tuple[str, ...], list[float], float, float], ...]:
        with self._lock:
            return tuple(
                (key, list(self._bucket_counts[key]), self._sums[key], self._counts[key])
                for key in self._bucket_counts
            )


Metric = Counter | Gauge | Histogram
_SimpleMetricT = TypeVar("_SimpleMetricT", Counter, Gauge)


class MetricsRegistry:
    """Process-local registry of counters/gauges/histograms.

    A `Collector` may also be registered: a zero-argument callable invoked at
    scrape time to compute gauges that are cheaper derived on demand than
    kept continuously up to date (e.g. a bounded aggregate database query).
    Collectors must themselves respect the same label-cardinality and
    tenant-safety rules as static metrics; they exist for values such as
    "projection lag across all tenants" that are naturally computed, not
    incrementally accumulated.
    """

    def __init__(self) -> None:
        self._metrics: dict[str, Metric] = {}
        self._collectors: list[Callable[[], None]] = []
        self._lock = threading.Lock()

    def counter(self, name: str, help_text: str, label_names: tuple[str, ...] = ()) -> Counter:
        return self._get_or_create(name, help_text, label_names, Counter)

    def gauge(self, name: str, help_text: str, label_names: tuple[str, ...] = ()) -> Gauge:
        return self._get_or_create(name, help_text, label_names, Gauge)

    def histogram(
        self,
        name: str,
        help_text: str,
        label_names: tuple[str, ...] = (),
        buckets: tuple[float, ...] = DEFAULT_LATENCY_BUCKETS,
    ) -> Histogram:
        with self._lock:
            existing = self._metrics.get(name)
            if existing is not None:
                if not isinstance(existing, Histogram):
                    raise ValueError(f"{name} already registered as {type(existing).__name__}")
                return existing
            metric = Histogram(name, help_text, label_names, buckets)
            self._metrics[name] = metric
            return metric

    def add_collector(self, collector: Callable[[], None]) -> None:
        """Register a zero-argument callable run at scrape time (best-effort;
        exceptions are swallowed so one broken collector cannot blank the
        whole /metrics response for every other metric)."""
        with self._lock:
            self._collectors.append(collector)

    def _get_or_create(
        self,
        name: str,
        help_text: str,
        label_names: tuple[str, ...],
        cls: type[_SimpleMetricT],
    ) -> _SimpleMetricT:
        with self._lock:
            existing = self._metrics.get(name)
            if existing is not None:
                if not isinstance(existing, cls):
                    raise ValueError(f"{name} already registered as {type(existing).__name__}")
                return existing
            metric = cls(name, help_text, label_names)
            self._metrics[name] = metric
            return metric

    def render(self) -> str:
        with self._lock:
            collectors = list(self._collectors)
        for collector in collectors:
            try:
                collector()
            except Exception:
                continue
        lines: list[str] = []
        with self._lock:
            metrics = list(self._metrics.values())
        for metric in metrics:
            lines.extend(_render_metric(metric))
        return "\n".join(lines) + "\n" if lines else ""


def _render_metric(metric: Metric) -> list[str]:
    lines = [
        f"# HELP {metric.name} {metric.help_text}",
        f"# TYPE {metric.name} {_type_of(metric)}",
    ]
    if isinstance(metric, Counter | Gauge):
        for labels, value in metric.samples():
            lines.append(f"{metric.name}{_render_labels(metric.label_names, labels)} {value}")
    elif isinstance(metric, Histogram):
        for labels, bucket_counts, total_sum, total_count in metric.samples():
            # `bucket_counts[i]` is already the cumulative ("le"-semantics)
            # count for `buckets[i]`: Histogram.observe() increments every
            # bucket whose bound is >= the observed value.
            for bound, cumulative in zip(metric.buckets, bucket_counts, strict=True):
                bucket_labels = metric.label_names + ("le",)
                bucket_values = labels + (_format_bound(bound),)
                lines.append(
                    f"{metric.name}_bucket{_render_labels(bucket_labels, bucket_values)} "
                    f"{cumulative}"
                )
            inf_labels = metric.label_names + ("le",)
            inf_values = labels + ("+Inf",)
            lines.append(
                f"{metric.name}_bucket{_render_labels(inf_labels, inf_values)} {total_count}"
            )
            sum_labels = _render_labels(metric.label_names, labels)
            lines.append(f"{metric.name}_sum{sum_labels} {total_sum}")
            lines.append(f"{metric.name}_count{sum_labels} {total_count}")
    return lines


def _format_bound(bound: float) -> str:
    if bound == int(bound):
        return str(int(bound))
    return str(bound)


def _type_of(metric: Metric) -> str:
    if isinstance(metric, Counter):
        return "counter"
    if isinstance(metric, Gauge):
        return "gauge"
    return "histogram"


_default_registry = MetricsRegistry()


def get_registry() -> MetricsRegistry:
    """Return the process-wide default metrics registry."""
    return _default_registry


def record_readiness(service: str, ready: bool, *, registry: MetricsRegistry | None = None) -> None:
    """Record the outcome of one readiness-probe evaluation as a gauge.

    Intended to be called from each service's existing `/readyz` handler
    (already invoked by the Kubernetes readiness probe every few seconds per
    `infra/kubernetes/base/*.yaml`), so readiness state becomes scrapeable
    via `/metrics` without a second, independent health-check mechanism.
    Label cardinality is bounded: `service` is a fixed, small,
    code-controlled name (one per EMG workload), never tenant or request
    data.
    """
    reg = registry or get_registry()
    gauge = reg.gauge(
        "emg_service_ready",
        "1 if the last /readyz evaluation reported ready, 0 if degraded/unavailable.",
        ("service",),
    )
    gauge.set(1.0 if ready else 0.0, labels=(service,))


def record_dependency_health(
    service: str,
    dependency: str,
    healthy: bool,
    *,
    registry: MetricsRegistry | None = None,
) -> None:
    """Record the health of one named upstream dependency (e.g. `postgres`,
    `neo4j`, `keycloak`, `audit_service`) as observed during a readiness
    check. `dependency` must be drawn from a small fixed vocabulary of
    dependency names known at code-review time, never a hostname, DSN, or
    other environment-supplied value, to keep this cardinality-bounded and
    free of connection-string/credential leakage.
    """
    reg = registry or get_registry()
    gauge = reg.gauge(
        "emg_dependency_healthy",
        "1 if the named upstream dependency was healthy at last check, 0 otherwise.",
        ("service", "dependency"),
    )
    gauge.set(1.0 if healthy else 0.0, labels=(service, dependency))
