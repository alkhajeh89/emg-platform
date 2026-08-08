"""Server-side session state for the Studio BFF (ADR-035 D-8).

Two distinct, separately-keyed record types, both server-side only, never
reflected into any browser-visible value beyond an opaque id:

- `PendingAuthorization` — the short-lived `state`/`nonce`/PKCE
  `code_verifier` bundle created by `GET /auth/login` and consumed exactly
  once by `GET /auth/callback`. Deleted immediately on first use (success or
  failure) — a second callback attempt with the same `state` can never
  succeed, independent of whatever code-reuse protection Keycloak itself
  applies (defense in depth, ADR-036 D-9-style "no silent replay").
- `HumanSession` — the authenticated session created on a successful
  callback. Holds the human's own verified Keycloak tokens server-side
  (ADR-035 D-8: "the browser never holds an access token, refresh token, ID
  token..."). A fresh session id is minted on every login; nothing here
  extends or reuses a prior session's id (session rotation after login).

Modeled on, but intentionally not importing, `services/identity/refresh_tokens.py`'s
Protocol-plus-adapters shape — that module is the legacy ROPC session system
this Phase 2B batch explicitly does not reuse or extend (see ADR-035's own
context section: `login_with_password` "is not a human session path").

**Correction-sprint Finding 1.** This module previously included a
`RedisSessionStore` adapter that connected to Redis directly from this
application. That is a confirmed violation of ADR-036 D-10.2: "No direct
datastore access from the browser or the BFF — PostgreSQL, Neo4j, Qdrant,
**Redis**, or any repository class." The prohibition names Redis explicitly
and unconditionally — there is no carve-out for ephemeral/auth-only state.
`RedisSessionStore` has been removed. `InMemorySessionStore` is the only
adapter for this batch, in every environment including production — a known,
documented limitation (single-process, sessions lost on restart, no
horizontal scale for the Studio BFF yet), recorded in
`docs/security/adr-038/07_PRODUCTION_CONFIGURATION.md`. Durable/shared
session storage requires a Platform-Service-fronted HTTP session API (the
BFF calling a service over HTTP, per ADR-036 D-1/D-3, never a datastore
directly) — that is future work, explicitly not designed here.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PendingAuthorization:
    state: str
    nonce: str
    code_verifier: str
    created_at: float


@dataclass(frozen=True, slots=True)
class HumanSession:
    session_id: str
    subject: str
    tenant_id: str
    classification_clearance: str
    roles: tuple[str, ...]
    access_token: str
    refresh_token: str | None
    access_token_expires_at: float
    created_at: float
    # Correction-sprint Finding 3: double-submit CSRF token, minted once at
    # login and echoed back by the browser (non-HttpOnly cookie + request
    # header) on every state-changing request. ADR-035 D-10: "SameSite alone
    # is not sufficient."
    csrf_token: str


class SessionStore(Protocol):
    def create_pending_authorization(self, pending: PendingAuthorization) -> None: ...

    def consume_pending_authorization(self, state: str) -> PendingAuthorization | None:
        """Return and delete the pending authorization for `state`, or
        `None` if it was never created, already consumed, or expired.
        Single-use by construction — there is no code path that returns the
        same record twice."""
        ...

    def create_session(self, session: HumanSession) -> None: ...

    def get_session(self, session_id: str) -> HumanSession | None:
        """Return `None` for a missing OR expired session — callers never
        need to separately check `access_token_expires_at` against session
        *existence*; expiry is enforced here."""
        ...

    def replace_session(self, session_id: str, session: HumanSession) -> None:
        """Overwrite an existing session's stored tokens in place (used
        after a server-side refresh) without changing the session id."""
        ...

    def delete_session(self, session_id: str) -> None: ...


def new_session_id() -> str:
    return uuid.uuid4().hex


class InMemorySessionStore:
    """Single-process, in-process adapter — the only session-storage adapter
    for this batch, in every environment (see the module docstring above:
    `RedisSessionStore` was removed as an ADR-036 D-10.2 violation).

    **Final correction-sprint Finding 1.** Because this store is genuinely
    long-lived for the life of the container (not a per-request scratch
    structure), it must bound its own memory growth independently of
    whatever cleanup `dependencies.py::current_session_dependency` performs
    on the read path:

    - `consume_pending_authorization` previously had NO expiry check at all
      — a `state` value from years-old, abandoned login attempt would still
      be accepted. It now rejects (returns `None`, evicting the record) any
      `PendingAuthorization` older than `pre_auth_ttl_seconds`.
    - Both `_pending` and `_sessions` are actively swept — not merely
      lazily evicted on a read for that exact key — on every write
      (`create_pending_authorization`, `create_session`), so an abandoned
      login flow or an abandoned session (created, never read again) cannot
      accumulate unboundedly across the container's lifetime. The sweep is
      O(n) amortized; there is no background task/thread — proportionate
      for a single-process, dev/first-production-batch store, not a general
      scheduling subsystem.
    """

    def __init__(self, *, pre_auth_ttl_seconds: int) -> None:
        self._pending: dict[str, PendingAuthorization] = {}
        self._sessions: dict[str, HumanSession] = {}
        self._pre_auth_ttl_seconds = pre_auth_ttl_seconds

    def _evict_expired(self) -> None:
        now = time.time()
        expired_pending = [
            state
            for state, pending in self._pending.items()
            if pending.created_at + self._pre_auth_ttl_seconds <= now
        ]
        for state in expired_pending:
            del self._pending[state]
        expired_sessions = [
            session_id
            for session_id, session in self._sessions.items()
            if session.access_token_expires_at <= now
        ]
        for session_id in expired_sessions:
            del self._sessions[session_id]

    def create_pending_authorization(self, pending: PendingAuthorization) -> None:
        self._evict_expired()
        self._pending[pending.state] = pending

    def consume_pending_authorization(self, state: str) -> PendingAuthorization | None:
        pending = self._pending.pop(state, None)
        if pending is None:
            return None
        if pending.created_at + self._pre_auth_ttl_seconds <= time.time():
            return None
        return pending

    def create_session(self, session: HumanSession) -> None:
        self._evict_expired()
        self._sessions[session.session_id] = session

    def get_session(self, session_id: str) -> HumanSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.access_token_expires_at <= time.time():
            del self._sessions[session_id]
            return None
        return session

    def replace_session(self, session_id: str, session: HumanSession) -> None:
        self._sessions[session_id] = session

    def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
