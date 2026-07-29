from __future__ import annotations

import pytest
from emg_api_contracts.security import (
    HttpRequestSecurityMiddleware,
    reject_unknown_environment,
)


async def _invoke(
    body: bytes,
    *,
    middleware: HttpRequestSecurityMiddleware,
    content_type: bytes = b"application/json",
) -> list[dict[str, object]]:
    received = False
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        nonlocal received
        if received:
            return {"type": "http.request", "body": b"", "more_body": False}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    await middleware(
        {"type": "http", "headers": [(b"content-type", content_type)]},
        receive,
        send,
    )
    return sent


def _ok_app() -> object:
    async def app(scope: object, receive: object, send: object) -> None:
        message = await receive()  # type: ignore[operator]
        assert message["body"]
        await send({"type": "http.response.start", "status": 204, "headers": []})  # type: ignore[operator]
        await send({"type": "http.response.body", "body": b""})  # type: ignore[operator]

    return app


@pytest.mark.asyncio
async def test_rejects_oversized_body() -> None:
    middleware = HttpRequestSecurityMiddleware(_ok_app(), max_body_bytes=4)  # type: ignore[arg-type]
    sent = await _invoke(b'{"x":1}', middleware=middleware)
    assert sent[0]["status"] == 413


@pytest.mark.asyncio
async def test_rejects_excessive_json_depth() -> None:
    middleware = HttpRequestSecurityMiddleware(_ok_app(), max_json_depth=2)  # type: ignore[arg-type]
    sent = await _invoke(b'{"x":{"y":1}}', middleware=middleware)
    assert sent[0]["status"] == 413


@pytest.mark.asyncio
async def test_rejects_oversized_collection() -> None:
    middleware = HttpRequestSecurityMiddleware(_ok_app(), max_collection_items=2)  # type: ignore[arg-type]
    sent = await _invoke(b'{"x":[1,2,3]}', middleware=middleware)
    assert sent[0]["status"] == 413


@pytest.mark.asyncio
async def test_replays_accepted_body_to_application() -> None:
    middleware = HttpRequestSecurityMiddleware(_ok_app())  # type: ignore[arg-type]
    sent = await _invoke(b'{"x":1}', middleware=middleware)
    assert sent[0]["status"] == 204


def test_unknown_production_environment_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMG_TEST_MISSPELLED", "unsafe")
    with pytest.raises(RuntimeError, match="EMG_TEST_MISSPELLED"):
        reject_unknown_environment("EMG_TEST_", {"known"})
