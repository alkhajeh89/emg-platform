"""Structured logger factory emitting the shared enterprise event schema.

ADR-015 Section 1 (Logs): "Every module emits structured, classification-
aware log events keyed to a common enterprise event schema (actor, module,
action, outcome, timestamp, correlation identifiers)."
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import MutableMapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .context import get_correlation_id

# logging.LoggerAdapter is only subscriptable (Generic) at runtime on
# Python 3.11+; typeshed marks it Generic unconditionally for type
# checking. Guarding the subscripted base behind TYPE_CHECKING keeps this
# module importable on the Python 3.10 baseline (pyproject.toml
# `requires-python = ">=3.10"`) while still giving mypy the type parameter
# it needs under `strict = true`.
if TYPE_CHECKING:
    _LoggerAdapterBase = logging.LoggerAdapter[logging.Logger]
else:
    _LoggerAdapterBase = logging.LoggerAdapter

# Maps the public ADR-015 schema field name (used in `extra=` and in the
# emitted JSON payload) to the internal LogRecord attribute name it is
# stored under. `logging.Logger.makeRecord` raises KeyError if `extra`
# supplies a key that collides with a reserved LogRecord attribute
# (`module`, `name`, `msg`, `args`, `levelname`, `filename`, ... — see
# https://docs.python.org/3/library/logging.html#logrecord-attributes).
# "module" and "name" both collide, so every schema field is namespaced
# with an `emg_` prefix internally; callers still pass and read the plain
# ADR-015 field names via `extra=` and the emitted JSON, respectively — this
# module is the only place the namespacing is visible.
_ENTERPRISE_SCHEMA_FIELDS: dict[str, str] = {
    "actor": "emg_actor",
    "module": "emg_module",
    "action": "emg_action",
    "outcome": "emg_outcome",
}


class _EnterpriseJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        for public_name, attr_name in _ENTERPRISE_SCHEMA_FIELDS.items():
            payload[public_name] = getattr(record, attr_name, None)
        return json.dumps(payload, default=str)


class _SchemaFieldAdapter(_LoggerAdapterBase):
    """Rewrites ADR-015 schema field names in `extra=` to their
    collision-safe internal attribute names before delegating to the
    underlying Logger, so callers use the plain schema names
    (`actor`, `module`, `action`, `outcome`) exactly as ADR-015 §1 names
    them, without needing to know about the LogRecord collision below."""

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        extra = kwargs.get("extra")
        if extra:
            remapped = dict(extra)
            for public_name, attr_name in _ENTERPRISE_SCHEMA_FIELDS.items():
                if public_name in remapped:
                    remapped[attr_name] = remapped.pop(public_name)
            kwargs["extra"] = remapped
        return msg, kwargs


def get_logger(module_name: str) -> logging.LoggerAdapter[logging.Logger]:
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
    return _SchemaFieldAdapter(logger, {})
