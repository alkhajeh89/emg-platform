"""Transport-level resource limits shared by EMG HTTP services."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

ASGIMessage = dict[str, Any]
ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
ASGISend = Callable[[ASGIMessage], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], ASGIReceive, ASGISend], Awaitable[None]]

DEFAULT_MAX_REQUEST_BODY_BYTES = 1_048_576
DEFAULT_MAX_JSON_DEPTH = 32
DEFAULT_MAX_JSON_COLLECTION_ITEMS = 1_000
DEFAULT_MAX_CONCURRENT_REQUESTS = 100


def reject_unknown_environment(prefix: str, allowed_fields: set[str]) -> None:
    """Fail closed on misspelled service configuration in production."""
    allowed = {f"{prefix}{field.upper()}" for field in allowed_fields}
    unknown = sorted(name for name in os.environ if name.startswith(prefix) and name not in allowed)
    if unknown:
        raise RuntimeError(f"unknown production configuration: {', '.join(unknown)}")


class HttpRequestSecurityMiddleware:
    """Reject resource-exhaustion payloads before endpoint validation.

    The limiter is deliberately transport-only: it knows nothing about EMG
    commands or domain objects. Concurrency is bounded per worker process;
    deployment-level replicas and ingress limits remain independent controls.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES,
        max_json_depth: int = DEFAULT_MAX_JSON_DEPTH,
        max_collection_items: int = DEFAULT_MAX_JSON_COLLECTION_ITEMS,
        max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS,
    ) -> None:
        if (
            min(
                max_body_bytes,
                max_json_depth,
                max_collection_items,
                max_concurrent_requests,
            )
            < 1
        ):
            raise ValueError("HTTP request limits must be positive")
        self._app = app
        self._max_body_bytes = max_body_bytes
        self._max_json_depth = max_json_depth
        self._max_collection_items = max_collection_items
        self._slots = asyncio.BoundedSemaphore(max_concurrent_requests)

    async def __call__(self, scope: dict[str, Any], receive: ASGIReceive, send: ASGISend) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        if self._slots.locked():
            await _send_error(send, 503, "request concurrency limit exceeded")
            return
        await self._slots.acquire()
        try:
            body = await self._read_body(receive)
            if body is None:
                await _send_error(send, 413, "request body limit exceeded")
                return
            if body and _is_json(scope):
                try:
                    payload = json.loads(body)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    await _send_error(send, 400, "malformed JSON request")
                    return
                if not _json_within_limits(
                    payload,
                    max_depth=self._max_json_depth,
                    max_collection_items=self._max_collection_items,
                ):
                    await _send_error(send, 413, "JSON structure limit exceeded")
                    return
            delivered = False

            async def replay_receive() -> ASGIMessage:
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}

            await self._app(scope, replay_receive, send)
        finally:
            self._slots.release()

    async def _read_body(self, receive: ASGIReceive) -> bytes | None:
        chunks: list[bytes] = []
        length = 0
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return b""
            chunk = message.get("body", b"")
            length += len(chunk)
            if length > self._max_body_bytes:
                return None
            chunks.append(chunk)
            if not message.get("more_body", False):
                return b"".join(chunks)


def _is_json(scope: dict[str, Any]) -> bool:
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() == b"content-type":
            content_type = bytes(raw_value)
            return content_type.split(b";", 1)[0].strip().lower() == b"application/json"
    return False


def _json_within_limits(value: object, *, max_depth: int, max_collection_items: int) -> bool:
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            return False
        if isinstance(current, dict):
            if len(current) > max_collection_items:
                return False
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            if len(current) > max_collection_items:
                return False
            stack.extend((item, depth + 1) for item in current)
    return True


async def _send_error(send: ASGISend, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}, separators=(",", ":")).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
