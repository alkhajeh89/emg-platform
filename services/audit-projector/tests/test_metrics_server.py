from __future__ import annotations

import socket
import urllib.error
import urllib.request

from emg_audit_projector.metrics_server import MetricsServer
from emg_telemetry.metrics import MetricsRegistry


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_metrics_server_serves_registry_content_at_metrics_path():
    registry = MetricsRegistry()
    registry.counter("emg_test_total", "help").inc()
    port = _free_port()
    server = MetricsServer(host="127.0.0.1", port=port, registry=registry)
    server.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as resp:
            body = resp.read().decode("utf-8")
            content_type = resp.headers.get("Content-Type")
    finally:
        server.stop()

    assert "emg_test_total 1.0" in body
    assert content_type is not None and content_type.startswith("text/plain")


def test_metrics_server_returns_404_for_any_other_path():
    port = _free_port()
    server = MetricsServer(host="127.0.0.1", port=port)
    server.start()
    try:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5)
            raised = False
            status = None
        except urllib.error.HTTPError as exc:
            raised = True
            status = exc.code
    finally:
        server.stop()

    assert raised
    assert status == 404


def test_metrics_server_stop_before_start_is_a_safe_no_op():
    server = MetricsServer(host="127.0.0.1", port=_free_port())
    server.stop()  # must not raise
