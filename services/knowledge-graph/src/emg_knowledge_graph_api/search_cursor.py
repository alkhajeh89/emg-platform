"""Opaque AES-256-GCM ADR-042 search cursors."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from emg_memory_graph import SEARCH_NORMALIZER_VERSION

ENDPOINT_BINDING = "POST:/v1/knowledge-graph/search"
CURSOR_VERSION = 1


class InvalidSearchCursor(ValueError):
    pass


@dataclass(frozen=True)
class CursorState:
    tenant: str
    query_digest: str
    revision: int
    tier: int
    node_id: str
    maximum_limit: int
    expires_at: datetime


class SearchCursorCodec:
    def __init__(
        self,
        active_key_id: str,
        keys: dict[str, bytes],
        ttl: timedelta,
        *,
        endpoint_binding: str = ENDPOINT_BINDING,
    ) -> None:
        if active_key_id not in keys or any(len(key) != 32 for key in keys.values()):
            raise ValueError("search cursor key ring requires an active 32-byte AES key")
        self._active = active_key_id
        self._keys = keys
        self._ttl = ttl
        self._endpoint_binding = endpoint_binding

    @staticmethod
    def digest(query: str) -> str:
        return hashlib.sha256(query.encode("utf-8")).hexdigest()

    def encode(
        self,
        tenant: str,
        query: str,
        revision: int,
        tier: int,
        node_id: str,
        maximum_limit: int,
        *,
        now: datetime | None = None,
        representation_expires_at: datetime | None = None,
    ) -> str:
        issued = now or datetime.now(timezone.utc)
        payload = json.dumps(
            {
                "v": CURSOR_VERSION,
                "nv": SEARCH_NORMALIZER_VERSION,
                "t": tenant,
                "q": self.digest(query),
                "r": revision,
                "tier": tier,
                "id": node_id,
                "iat": int(issued.timestamp()),
                "limit": maximum_limit,
                "exp": int(
                    min(
                        issued + self._ttl,
                        representation_expires_at or issued + self._ttl,
                    ).timestamp()
                ),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        nonce = os.urandom(12)
        aad = f"{CURSOR_VERSION}:{self._active}:{self._endpoint_binding}".encode()
        encrypted = AESGCM(self._keys[self._active]).encrypt(nonce, payload, aad)
        envelope = {
            "v": CURSOR_VERSION,
            "kid": self._active,
            "n": _b64(nonce),
            "c": _b64(encrypted),
        }
        return _b64(json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode())

    def decode(
        self, cursor: str, tenant: str, query: str, *, now: datetime | None = None
    ) -> CursorState:
        try:
            if len(cursor) > 4096:
                raise ValueError
            envelope = json.loads(_unb64(cursor))
            if not isinstance(envelope, dict) or set(envelope) != {"v", "kid", "n", "c"}:
                raise ValueError
            kid = envelope["kid"]
            key = self._keys[kid]
            aad = f"{envelope['v']}:{kid}:{self._endpoint_binding}".encode()
            data = json.loads(
                AESGCM(key).decrypt(_unb64(envelope["n"]), _unb64(envelope["c"]), aad)
            )
            if not isinstance(data, dict) or set(data) != {
                "v",
                "nv",
                "t",
                "q",
                "r",
                "tier",
                "id",
                "limit",
                "iat",
                "exp",
            }:
                raise ValueError
            current = now or datetime.now(timezone.utc)
            if (
                data["v"] != CURSOR_VERSION
                or data["nv"] != SEARCH_NORMALIZER_VERSION
                or data["t"] != tenant
                or data["q"] != self.digest(query)
                or current.timestamp() >= data["exp"]
            ):
                raise ValueError
            return CursorState(
                data["t"],
                data["q"],
                int(data["r"]),
                int(data["tier"]),
                str(data["id"]),
                int(data["limit"]),
                datetime.fromtimestamp(data["exp"], timezone.utc),
            )
        except Exception as exc:
            raise InvalidSearchCursor("invalid search continuation") from exc


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
