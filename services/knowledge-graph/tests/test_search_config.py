import pytest
from emg_knowledge_graph_api.config import Settings, validate_secure_transport
from pydantic import ValidationError


def test_approved_search_profile_defaults():
    settings = Settings()
    assert settings.search_cursor_default_ttl_seconds == 15 * 60
    assert settings.search_cursor_max_ttl_seconds == 30 * 60
    assert settings.search_representation_retention_seconds == 60 * 60
    assert settings.search_cleanup_interval_seconds == 15 * 60
    assert settings.search_cleanup_batch_size == 500
    assert settings.search_candidate_batch_size == 200
    assert settings.search_candidate_work_ceiling == 10_000


def test_cursor_ttl_cannot_exceed_representation_retention():
    with pytest.raises(ValidationError):
        Settings(
            search_cursor_max_ttl_seconds=3601,
            search_representation_retention_seconds=3600,
        )


def test_cursor_key_ring_uses_256_bit_keys():
    with pytest.raises(ValidationError):
        Settings(search_cursor_keys_json='{"development":"c2hvcnQ="}')


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("search_cleanup_batch_size", 5_001),
        ("search_candidate_batch_size", 1_001),
        ("search_candidate_work_ceiling", 10_001),
    ],
)
def test_operational_search_controls_have_hard_startup_bounds(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_production_rejects_development_issuance_key_after_other_gates(tmp_path):
    policy = tmp_path / "policy.yaml"
    catalog = tmp_path / "catalog.json"
    policy.write_text("rules: []", encoding="utf-8")
    catalog.write_text("{}", encoding="utf-8")
    settings = Settings(
        deployment_environment="production",
        store_backend="postgres",
        keycloak_base_url="https://keycloak.example.gov",
        audit_service_base_url="https://audit.example.gov",
        postgres_dsn="postgresql://runtime:secret@postgres/emg?sslmode=verify-full",
        audit_producer_client_secret="production-secret",
        policy_config_path=policy,
        schema_catalog_path=catalog,
    )
    with pytest.raises(RuntimeError, match="development key"):
        validate_secure_transport(settings)
