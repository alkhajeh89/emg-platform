from __future__ import annotations

import re
import threading

import pytest
from emg_telemetry.metrics import MAX_LABEL_VALUES_PER_METRIC, MetricsRegistry


def test_counter_renders_prometheus_text_exposition_format():
    registry = MetricsRegistry()
    counter = registry.counter("emg_test_total", "A test counter.", ("outcome",))
    counter.inc(labels=("success",))
    counter.inc(2.0, labels=("success",))
    counter.inc(labels=("failure",))

    text = registry.render()

    assert "# HELP emg_test_total A test counter." in text
    assert "# TYPE emg_test_total counter" in text
    assert 'emg_test_total{outcome="success"} 3.0' in text
    assert 'emg_test_total{outcome="failure"} 1.0' in text


def test_gauge_set_is_idempotent_overwrite():
    registry = MetricsRegistry()
    gauge = registry.gauge("emg_test_gauge", "A test gauge.")
    gauge.set(5.0)
    gauge.set(9.0)

    text = registry.render()

    assert "emg_test_gauge 9.0" in text
    assert "emg_test_gauge 5.0" not in text


def test_histogram_buckets_are_cumulative_and_include_inf_and_sum_count():
    registry = MetricsRegistry()
    hist = registry.histogram("emg_test_duration_seconds", "A test histogram.")
    hist.observe(0.001)
    hist.observe(3.0)

    text = registry.render()

    assert 'emg_test_duration_seconds_bucket{le="0.005"} 1.0' in text
    assert 'emg_test_duration_seconds_bucket{le="+Inf"} 2.0' in text
    assert "emg_test_duration_seconds_sum 3.001" in text
    assert "emg_test_duration_seconds_count 2.0" in text


def test_label_values_are_escaped_against_injection_into_exposition_format():
    """A label value containing a quote or newline must not be able to
    break out of the rendered label block and forge extra metric lines --
    this is the mechanism that keeps untrusted-ish strings (e.g. a
    failure_class derived from an exception type name) from corrupting the
    /metrics response for every other metric. The raw text may still
    contain the injected substrings (escaping preserves content), but it
    must never turn into a structurally separate line/metric."""
    registry = MetricsRegistry()
    counter = registry.counter("emg_test_total", "help", ("failure_class",))
    counter.inc(labels=('bad"} emg_injected 999\n# TYPE evil counter\nx{a="',))

    lines = registry.render().splitlines()

    assert not any(line.startswith("emg_injected") for line in lines)
    assert not any(line.startswith("# TYPE evil") for line in lines)
    # The whole payload must land inside exactly one well-formed metric line,
    # not spill across structurally separate lines of its own.
    matching = [line for line in lines if line.startswith("emg_test_total{")]
    assert len(matching) == 1
    assert matching[0].endswith(" 1.0")


def test_cardinality_guard_bounds_distinct_label_combinations():
    """RC-C adversarial requirement: alerts/metrics must be resistant to a
    cardinality bomb (e.g. an attacker or bug driving many distinct label
    values). Once the cap is reached, further distinct combinations must
    collapse into a fixed "other" bucket rather than growing without bound."""
    registry = MetricsRegistry()
    counter = registry.counter("emg_test_total", "help", ("route",))
    for i in range(MAX_LABEL_VALUES_PER_METRIC + 50):
        counter.inc(labels=(f"/unique/{i}",))

    samples = counter.samples()

    assert len(samples) <= MAX_LABEL_VALUES_PER_METRIC + 1  # +1 for the "other" bucket
    other_total = dict(samples).get(("other",))
    assert other_total is not None and other_total >= 50


def test_metric_name_and_label_name_validation_rejects_malformed_input():
    registry = MetricsRegistry()
    with pytest.raises(ValueError):
        registry.counter("not a valid metric name", "help")
    with pytest.raises(ValueError):
        registry.counter("emg_valid_name", "help", ("not a valid label",))


def test_registering_same_name_twice_with_different_type_raises():
    registry = MetricsRegistry()
    registry.counter("emg_dup", "help")
    with pytest.raises(ValueError):
        registry.gauge("emg_dup", "help")


def test_registering_same_name_twice_with_same_type_returns_same_instance():
    registry = MetricsRegistry()
    first = registry.counter("emg_shared", "help")
    second = registry.counter("emg_shared", "help")
    assert first is second


def test_collector_is_invoked_at_render_time():
    registry = MetricsRegistry()
    calls = []

    def collector():
        calls.append(1)
        registry.gauge("emg_from_collector", "help").set(float(len(calls)))

    registry.add_collector(collector)
    registry.render()
    second_render = registry.render()

    assert calls == [1, 1]  # invoked exactly once per render() call
    assert "emg_from_collector 2.0" in second_render


def test_broken_collector_does_not_blank_other_metrics():
    registry = MetricsRegistry()
    registry.counter("emg_survives", "help").inc()

    def broken_collector():
        raise RuntimeError("boom")

    registry.add_collector(broken_collector)

    text = registry.render()

    assert "emg_survives 1.0" in text


def test_counter_inc_rejects_negative_amount():
    registry = MetricsRegistry()
    counter = registry.counter("emg_test_total", "help")
    with pytest.raises(ValueError):
        counter.inc(-1.0)


def test_label_arity_mismatch_raises():
    registry = MetricsRegistry()
    counter = registry.counter("emg_test_total", "help", ("a", "b"))
    with pytest.raises(ValueError):
        counter.inc(labels=("only_one",))


def test_concurrent_increments_are_not_lost():
    registry = MetricsRegistry()
    counter = registry.counter("emg_concurrent_total", "help")

    def hammer():
        for _ in range(1000):
            counter.inc()

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    text = registry.render()
    match = re.search(r"emg_concurrent_total (\d+(?:\.\d+)?)", text)
    assert match is not None
    assert float(match.group(1)) == 8000.0
