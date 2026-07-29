import pytest
from emg_audit_service.config import Settings, validate_runtime_configuration
from pydantic import ValidationError


def test_unknown_audit_backend_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(store_backend="postgress")


def test_production_rejects_memory_storage() -> None:
    with pytest.raises(RuntimeError, match="in-memory store backend"):
        validate_runtime_configuration(
            Settings(deployment_environment="production", store_backend="memory")
        )


@pytest.mark.parametrize("environment", ["development", "test"])
def test_non_production_accepts_memory_storage(environment: str) -> None:
    validate_runtime_configuration(
        Settings(deployment_environment=environment, store_backend="memory")
    )


def test_production_accepts_postgres_storage() -> None:
    validate_runtime_configuration(
        Settings(deployment_environment="production", store_backend="postgres")
    )
