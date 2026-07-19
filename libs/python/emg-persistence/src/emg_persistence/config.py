"""Configuration for emg-persistence (Phase 2 — Persistence Binding).

``PersistenceSettings`` is an immutable, environment-driven settings model
(``pydantic-settings``) describing how to reach the datastores. Per the approved
architecture (Revision 3):

* **PostgreSQL is authoritative** (ADR-1). Whether persistence is "configured" is
  therefore determined by the presence of ``postgres_dsn`` — the authoritative
  datastore — via :pyattr:`PersistenceSettings.is_persistence_configured`.
* **Neo4j is a serving projection only** (never on the write path); its
  connection settings are optional and, when absent, reads fall back to
  PostgreSQL (§5.1) in later sprints.

Sprint 1 defines the settings surface and validates it (shape/bounds only — no
connections are opened). Secrets use ``SecretStr`` so they are never rendered in
logs or tracebacks.
"""

from __future__ import annotations

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_POSTGRES_SCHEMES = ("postgresql://", "postgres://")
_NEO4J_SCHEMES = ("neo4j://", "neo4j+s://", "neo4j+ssc://", "bolt://", "bolt+s://", "bolt+ssc://")


class PersistenceSettings(BaseSettings):
    """Immutable persistence configuration, read from ``EMG_PERSISTENCE_*`` env
    vars (or passed explicitly).

    All datastore fields are optional. With no ``postgres_dsn`` the package
    operates in in-memory mode (dev/tests); supplying it selects the persistent
    backend (wired in later sprints).
    """

    model_config = SettingsConfigDict(
        env_prefix="EMG_PERSISTENCE_",
        frozen=True,
        extra="forbid",
    )

    # --- Datastore connections (all optional) -------------------------------
    postgres_dsn: str | None = Field(
        default=None,
        description="PostgreSQL DSN for the authoritative revision log (ADR-1).",
    )
    neo4j_uri: str | None = Field(
        default=None,
        description="Neo4j URI for the serving projection (ADR-1); optional.",
    )
    neo4j_user: str | None = Field(default=None, description="Neo4j username.")
    neo4j_password: SecretStr | None = Field(
        default=None, description="Neo4j password (never logged)."
    )

    # --- Pool / timeout knobs (bounded) -------------------------------------
    postgres_pool_min_size: int = Field(
        default=1, ge=0, description="Minimum PostgreSQL pool connections."
    )
    postgres_pool_max_size: int = Field(
        default=10, ge=1, description="Maximum PostgreSQL pool connections."
    )
    neo4j_max_pool_size: int = Field(
        default=10, ge=1, description="Maximum Neo4j driver pool connections."
    )
    connect_timeout_seconds: float = Field(
        default=10.0, gt=0, description="Connection timeout in seconds."
    )

    @field_validator("postgres_dsn")
    @classmethod
    def _validate_postgres_dsn(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(_POSTGRES_SCHEMES):
            raise ValueError(
                f"postgres_dsn must start with one of {_POSTGRES_SCHEMES}; got a different scheme"
            )
        return value

    @field_validator("neo4j_uri")
    @classmethod
    def _validate_neo4j_uri(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(_NEO4J_SCHEMES):
            raise ValueError(
                f"neo4j_uri must start with one of {_NEO4J_SCHEMES}; got a different scheme"
            )
        return value

    @model_validator(mode="after")
    def _validate_pool_bounds(self) -> PersistenceSettings:
        if self.postgres_pool_max_size < self.postgres_pool_min_size:
            raise ValueError(
                "postgres_pool_max_size must be >= postgres_pool_min_size "
                f"({self.postgres_pool_max_size} < {self.postgres_pool_min_size})"
            )
        return self

    @property
    def is_persistence_configured(self) -> bool:
        """True iff the authoritative datastore (PostgreSQL) is configured.

        PostgreSQL is the source of truth (ADR-1), so its DSN — not Neo4j's —
        decides whether the persistent backend should be built. When ``False``
        the factory returns the in-memory store (dev/tests).
        """
        return self.postgres_dsn is not None
