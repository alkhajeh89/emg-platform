"""Authenticated-principal value type shared across services."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Principal:
    """The authenticated identity attached to a request, once Module 4/5
    are implemented. Fields mirror the claims Module 5's Policy Enforcement
    Point requires (Engineering Backlog v1.0, US-02 acceptance criteria).
    """

    subject: str
    roles: tuple[str, ...] = field(default_factory=tuple)
    attributes: dict[str, str] = field(default_factory=dict)
