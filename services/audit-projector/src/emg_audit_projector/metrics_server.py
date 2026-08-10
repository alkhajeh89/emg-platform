"""Minimal `/metrics` HTTP server for the headless Audit Projector worker.

Every other EMG HTTP service exposes `/metrics` as an ordinary FastAPI route
on its existing app port (`emg_telemetry.http_metrics.metrics_router`), but
the Audit Projector is a headless worker with no HTTP server at all today
(`infra/kubernetes/base/audit-projector.yaml`'s liveness/readiness probes are
`exec` file-sentinel checks, not HTTP). Standing up a full FastAPI app just
to serve one read-only text endpoint would be a heavier, less honest change
than what this worker needs, so this module uses only the standard library
(`http.server`), matching the "no new production dependency" constraint
`emg_telemetry.metrics` documents.

Not started by default at import time: `ProjectorRuntime` starts and stops
it explicitly alongside the worker thread, on the port `Settings.metrics_port`
declares (see `infra/kubernetes/base/audit-projector.yaml`'s `metrics`
container port, added alongside this change).
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from emg_telemetry.metrics import MetricsRegistry, get_registry


def _handler_factory(registry: MetricsRegistry) -> type[BaseHTTPRequestHandler]:
    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib method name
            if self.path != "/metrics":
                self.send_response(404)
                self.end_headers()
                return
            body = registry.render().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            # Suppress the default stderr access log: this endpoint is
            # scraped every few seconds and would otherwise flood worker
            # logs with no operational value.
            return

    return MetricsHandler


class MetricsServer:
    """A background-thread HTTP server serving only `GET /metrics`.

    The socket is bound in `start()`, not `__init__()`, so constructing (but
    never starting) a `ProjectorRuntime` -- e.g. in a unit test that
    monkeypatches everything else -- never claims a port as a side effect.
    """

    def __init__(
        self, *, host: str = "0.0.0.0", port: int, registry: MetricsRegistry | None = None
    ) -> None:
        self._host = host
        self._port = port
        self._registry = registry or get_registry()
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    def start(self) -> None:
        server = ThreadingHTTPServer((self._host, self._port), _handler_factory(self._registry))
        self._server = server
        thread = Thread(target=server.serve_forever, name="audit-projector-metrics", daemon=True)
        thread.start()
        self._thread = thread

    def stop(self) -> None:
        server = self._server
        if server is None:
            return
        server.shutdown()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
        server.server_close()
        self._server = None
        self._thread = None
