import pytest
from emg_identity.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        keycloak_base_url="http://keycloak.test",
        keycloak_realm="emg-test",
        keycloak_client_id="test-client",
        keycloak_client_secret="test-secret",
        # >= 32 bytes to avoid PyJWT's InsecureKeyLengthWarning for HS256.
        session_signing_key="test-signing-key-not-for-prod-min-32-bytes",
        access_token_ttl_seconds=900,
        refresh_token_ttl_seconds=43200,
        token_issuer="emg-identity-service",
        token_audience="emg-platform",
    )
