"""Shared helper: the real, unmodified `emg_audit_service` FastAPI app,
backed by isolated in-process test persistence (`InMemoryAuditEventStore`)
and validating service tokens against the REAL isolated verification
Keycloak's JWKS over HTTP -- not a locally injected key.

This is the user-approved "narrowest repository-faithful test harness"
path (see the ADR-038 verification approval message): it reuses the exact
pattern services/audit/tests/conftest.py already establishes for testing
the audit service without Docker/PostgreSQL/a live Keycloak, the one
difference being that THIS harness points ServiceTokenValidator at a real,
running Keycloak (the isolated verification one) rather than a locally
injected RSA key, because real Keycloak-issued tokens are stronger
evidence for this verification than hand-crafted test JWTs.

Never touches the shared, already-running `emg-audit` container on :8002.
Never modifies any file under services/audit.
"""

from __future__ import annotations

from emg_audit_pipeline import InMemoryAuditEventStore, InMemoryCustodyEventStore
from emg_audit_service.authn import (
    ServiceTokenValidator,
    service_token_validator_dependency,
    settings_dependency,
)
from emg_audit_service.config import Settings
from emg_audit_service.main import create_app
from emg_audit_service.store import custody_store_dependency, store_dependency
from fastapi.testclient import TestClient

AUDIT_AUDIENCE = "emg-verification-audit-audience"


def audit_settings(env: dict) -> Settings:
    return Settings(
        store_backend="memory",
        keycloak_base_url=env["base_url"],
        keycloak_realm=env["realm"],
        service_token_audience=AUDIT_AUDIENCE,
    )


def build_audit_client(env: dict) -> tuple[TestClient, InMemoryAuditEventStore]:
    """Returns (TestClient wrapping the real audit app, the in-memory event
    store backing it, so tests can also assert directly against stored
    events without re-parsing HTTP responses)."""
    settings = audit_settings(env)
    store = InMemoryAuditEventStore()
    custody_store = InMemoryCustodyEventStore()

    app = create_app()
    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[service_token_validator_dependency] = lambda: ServiceTokenValidator(
        settings
    )
    app.dependency_overrides[store_dependency] = lambda: store
    app.dependency_overrides[custody_store_dependency] = lambda: custody_store
    return TestClient(app), store


class _FailingAuditEventStore(InMemoryAuditEventStore):
    """Simulates the audit service itself being unavailable (ADR-036 D-9:
    'Audit service unavailable -> Block governed actions -- fail closed').
    Real subclass of the real in-memory store (repository-faithful shape),
    with append() replaced to raise -- not a bespoke mock unrelated to the
    production type."""

    def append(self, *args, **kwargs):  # noqa: D102 - matches base signature
        raise RuntimeError("simulated audit store outage")


def build_audit_client_with_failing_store(env: dict) -> TestClient:
    """raise_server_exceptions=False: makes TestClient behave like a real
    HTTP client observing the wire response (whatever main.py's exception
    handling actually sends back), instead of pytest's default
    debug-friendly re-raise of the underlying Python exception. This is
    what the test needs to assert on -- what a caller over the network
    would see -- not a property of this test harness."""
    settings = audit_settings(env)
    app = create_app()
    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[service_token_validator_dependency] = lambda: ServiceTokenValidator(
        settings
    )
    app.dependency_overrides[store_dependency] = lambda: _FailingAuditEventStore()
    app.dependency_overrides[custody_store_dependency] = lambda: InMemoryCustodyEventStore()
    return TestClient(app, raise_server_exceptions=False)
