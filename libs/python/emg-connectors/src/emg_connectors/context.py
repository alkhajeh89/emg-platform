"""Connector context + session (FEAT-13-1).

`ConnectorContext` is the immutable ambient context an operation would run under
(correlation id, owner, an explicit `as_of` timestamp, and the bound
configuration/authentication *declarations*). `ConnectorSession` is a logical
session value object — an identifier plus the context — **not** a network
connection. Nothing here opens a socket or performs I/O.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .configuration import ConnectorAuthentication, ConnectorConfiguration
from .labels import SafeLabel


class ConnectorContext(BaseModel):
    """Immutable ambient context for a connector operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: SafeLabel
    as_of: datetime
    owner: SafeLabel | None = None
    configuration: ConnectorConfiguration | None = None
    authentication: ConnectorAuthentication | None = None


class ConnectorSession(BaseModel):
    """An immutable logical session value object (not a transport connection)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SafeLabel
    connector_id: SafeLabel
    opened_at: datetime
    context: ConnectorContext
