"""Optional integration tests against a real, locally-running Keycloak
container (the one started by `docker-compose.yml`, seeded from
tools/seed-data/keycloak/emg-realm.json).

Skipped by default (see `_skip_reason` below) so `pytest -q libs services`
never requires Docker or a live Keycloak — every other Sprint 1-3 test uses
`httpx.MockTransport` or a locally-generated RSA keypair instead, per the
user's instruction: "use mocked external identity-provider interactions
where Docker or live Keycloak execution is unavailable... also provide a
clearly documented integration-test procedure for running against the local
Keycloak container."

--- Procedure to run these tests against a real Keycloak -------------------

1. From the repository root, start the local stack:

       docker compose up -d keycloak

   Wait for Keycloak to report healthy (`docker compose ps`), then confirm
   the emg-realm.json seed was imported (Keycloak's dev container imports
   any realm file mounted at its import path on first boot — see
   docker-compose.yml's `keycloak` service and
   tools/seed-data/keycloak/README.md for the exact mount and import flags).

2. Export the following so these tests point at that Keycloak instead of
   using the `settings` fixture's `http://keycloak.test` placeholder:

       export EMG_IDENTITY_KEYCLOAK_BASE_URL=http://localhost:8080
       export EMG_IDENTITY_KEYCLOAK_REALM=emg
       export EMG_IDENTITY_RUN_LIVE_KEYCLOAK_TESTS=1

3. Run just this file:

       pytest -q services/identity/tests/test_integration_live_keycloak.py \\
           --import-mode=importlib

Each test below re-derives Settings from the environment (not the `settings`
fixture) specifically so it exercises the real local-dev secrets seeded into
emg-realm.json, and is independently skipped unless
EMG_IDENTITY_RUN_LIVE_KEYCLOAK_TESTS=1 is set.
"""

from __future__ import annotations

import os

import pytest
from emg_identity.config import Settings
from emg_identity.keycloak_client import KeycloakClient
from emg_identity.service_token_validator import ServiceTokenValidator

_RUN_LIVE = os.environ.get("EMG_IDENTITY_RUN_LIVE_KEYCLOAK_TESTS") == "1"
_skip_reason = (
    "Live Keycloak integration tests are opt-in — set "
    "EMG_IDENTITY_RUN_LIVE_KEYCLOAK_TESTS=1 with a running local Keycloak "
    "(see this file's module docstring for the full procedure)."
)


def _live_settings() -> Settings:
    return Settings(
        keycloak_base_url=os.environ.get("EMG_IDENTITY_KEYCLOAK_BASE_URL", "http://localhost:8080"),
        keycloak_realm=os.environ.get("EMG_IDENTITY_KEYCLOAK_REALM", "emg"),
    )


@pytest.mark.skipif(not _RUN_LIVE, reason=_skip_reason)
@pytest.mark.asyncio
async def test_live_client_credentials_grant_against_seeded_service_client():
    """Exercises the real OAuth 2.0 Client Credentials flow end-to-end
    against the emg-svc-authorization client seeded in emg-realm.json."""
    settings = _live_settings()
    client = KeycloakClient(settings)
    try:
        result = await client.client_credentials_token(
            client_id="emg-svc-authorization",
            client_secret=os.environ.get(
                "EMG_SVC_AUTHORIZATION_SECRET",
                "emg_svc_authorization_local_dev_secret_do_not_use_in_prod",
            ),
        )
        assert result.access_token
        assert result.refresh_token is None
    finally:
        await client.aclose()


@pytest.mark.skipif(not _RUN_LIVE, reason=_skip_reason)
@pytest.mark.asyncio
async def test_live_service_token_validates_against_real_jwks():
    """Fetches a real token from Keycloak, then validates it through
    ServiceTokenValidator's DEFAULT (JWKS-backed) signing_key_resolver —
    the one code path every other test in this suite deliberately bypasses
    by injecting a local keypair."""
    settings = _live_settings()
    client = KeycloakClient(settings)
    try:
        result = await client.client_credentials_token(
            client_id="emg-svc-authorization",
            client_secret=os.environ.get(
                "EMG_SVC_AUTHORIZATION_SECRET",
                "emg_svc_authorization_local_dev_secret_do_not_use_in_prod",
            ),
        )
    finally:
        await client.aclose()

    validator = ServiceTokenValidator(settings)  # default JWKS resolver
    principal = validator.validate(result.access_token)
    assert principal.client_id == "emg-svc-authorization"
    assert principal.service_name == "authorization"
