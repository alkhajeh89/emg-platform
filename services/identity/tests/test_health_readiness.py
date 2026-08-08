from __future__ import annotations

import asyncio
from pathlib import Path

from emg_identity import health
from emg_identity.config import Settings


def test_production_readiness_fails_closed_when_mandatory_dependency_is_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(health, "_keycloak_ready", lambda _settings: _result(False))
    monkeypatch.setattr(health, "_postgres_ready", lambda _settings: _result(True))
    monkeypatch.setattr(health, "_audit_ready", lambda _settings: _result(True))
    monkeypatch.setattr(health.os, "access", lambda *_args: True)
    settings = Settings(
        deployment_environment="production",
        audit_spool_path=tmp_path / "events.jsonl",
    )

    result = asyncio.run(health.readiness(settings))

    assert result["status"] == "unavailable"
    assert result["keycloak_available"] is False


async def _result(value: bool) -> bool:
    return value
