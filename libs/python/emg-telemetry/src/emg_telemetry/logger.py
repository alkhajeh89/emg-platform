"""Structured logger factory emitting the shared enterprise event schema.

ADR-015 Section 1 (Logs): "Every module emits structured, classification-
aware log events keyed to a common enterprise event schema (actor, module,
action, outcome, timestamp, correlation identifiers)."
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from .context import get_correlation_id

_ENTERPRISE_SCHEMA_FIELDS = ("actor", "module", "action", "outcome")


class _EnterpriseJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        for field in _ENTERPRISE_SCHEMA_FIELDS:
            payload[field] = getattr(record, field, None)
        return json.dumps(payload, default=str)


def get_logger(module_name: str) -> logging.Logger:
    """Return a logger pre-configured to emit the shared enterprise event
    schema as JSON to stdout.

    Usage:
        log = get_logger("identity")
        log.info("login succeeded", extra={"actor": user_id, "module": "identity",
                                            "action": "login", "outcome": "success"})
    """
    logger = logging.getLogger(f"emg.{module_name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_EnterpriseJsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
