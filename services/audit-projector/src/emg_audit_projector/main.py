"""Process entry point and bounded SIGTERM/SIGINT drain."""

from __future__ import annotations

import signal

from emg_telemetry import get_logger

from .config import Settings
from .runtime import ProjectorRuntime

_log = get_logger("audit-projector")


def main() -> None:
    runtime = ProjectorRuntime(Settings())

    def request_shutdown(signum: int, frame: object) -> None:
        del frame
        drained = runtime.stop()
        _log.info(
            "projector shutdown requested",
            extra={
                "actor": "process",
                "module": "audit-projector",
                "action": "shutdown",
                "outcome": "drained" if drained else "deadline_exceeded",
                "signal": signum,
            },
        )

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    try:
        runtime.start()
        runtime.wait()
    finally:
        runtime.stop()
        runtime.close()


if __name__ == "__main__":  # pragma: no cover
    main()
