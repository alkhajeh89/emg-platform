from __future__ import annotations

import asyncio

from emg_studio_bff.config import Settings
from emg_studio_bff.routers import health
from fastapi import Response


class _OkResponse:
    status_code = 200


class _RecordingClient:
    urls: list[str] = []

    def __init__(self, *, timeout: float) -> None:
        assert timeout == 0.25

    async def __aenter__(self) -> _RecordingClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get(self, url: str) -> _OkResponse:
        self.urls.append(url)
        return _OkResponse()


def test_readiness_uses_only_public_metadata_and_downstream_health(
    monkeypatch,
) -> None:
    _RecordingClient.urls = []
    monkeypatch.setattr(health.httpx, "AsyncClient", _RecordingClient)
    settings = Settings(readiness_timeout_seconds=0.25)
    response = Response()

    result = asyncio.run(health.readyz(response, settings))

    assert result["status"] == "ready"
    assert response.status_code == 200
    assert _RecordingClient.urls == [
        "http://localhost:8080/realms/emg/.well-known/openid-configuration",
        "http://localhost:8080/realms/emg/protocol/openid-connect/certs",
        "http://localhost:8003/readyz",
    ]
    assert not any("/token" in url or "/auth" in url for url in _RecordingClient.urls)
