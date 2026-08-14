from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from emg_identity.recovery_gate import RecoveryGateDenied
from emg_identity.refresh_tokens import PostgresRefreshTokenStore

_POSTGRES_DSN = os.environ.get("EMG_IDENTITY_TEST_POSTGRES_DSN")

requires_postgres = pytest.mark.skipif(
    not _POSTGRES_DSN, reason="requires EMG_IDENTITY_TEST_POSTGRES_DSN"
)


@requires_postgres
def test_postgres_rotation_is_single_use_and_stores_only_hashes() -> None:
    import psycopg

    assert _POSTGRES_DSN is not None
    store = PostgresRefreshTokenStore(_POSTGRES_DSN)
    family_id = f"family-{uuid4()}"
    first_token_id = f"refresh-{uuid4()}"
    next_token_id = f"refresh-{uuid4()}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    store.register(family_id, first_token_id, expires_at)
    assert store.rotate(family_id, first_token_id, next_token_id, expires_at) is True
    assert store.rotate(family_id, first_token_id, next_token_id, expires_at) is False
    assert store.family_is_active(family_id) is False

    with psycopg.connect(_POSTGRES_DSN) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT family_hash
            FROM emg_identity.identity_refresh_token_families
            WHERE family_hash = %s OR family_hash = %s
            """,
            (family_id, first_token_id),
        )
        assert cursor.fetchall() == []
        cursor.execute(
            """
            SELECT token_hash
            FROM emg_identity.identity_refresh_tokens
            WHERE token_hash = %s OR token_hash = %s
            """,
            (first_token_id, next_token_id),
        )
        assert cursor.fetchall() == []


@requires_postgres
def test_request_time_recovery_gate_blocks_operations_on_mismatch_and_allows_on_match(
    tmp_path: Path,
) -> None:
    """ADR-043 Amendment 1 A8: the request-time gate re-checks the full pair
    on every operation, independent of Kubernetes readiness."""

    assert _POSTGRES_DSN is not None
    with psycopg.connect(_POSTGRES_DSN) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT reconciled_generation::text, reconciled_authority_revision "
            "FROM emg_identity.identity_recovery_state"
        )
        current_generation, current_revision = cursor.fetchone()

    matching_file = tmp_path / "matching.json"
    matching_file.write_text(
        f'{{"generation": "{current_generation}", "authority_revision": "{current_revision}"}}',
        encoding="utf-8",
    )
    mismatched_file = tmp_path / "mismatched.json"
    mismatched_file.write_text(
        '{"generation": "stale-generation", "authority_revision": "0"}', encoding="utf-8"
    )

    family_id = f"family-{uuid4()}"
    token_id = f"refresh-{uuid4()}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    gated_store = PostgresRefreshTokenStore(_POSTGRES_DSN, recovery_authority_file=mismatched_file)
    with pytest.raises(RecoveryGateDenied):
        gated_store.register(family_id, token_id, expires_at)
    with pytest.raises(RecoveryGateDenied):
        gated_store.family_is_active(family_id)

    matching_store = PostgresRefreshTokenStore(_POSTGRES_DSN, recovery_authority_file=matching_file)
    matching_store.register(family_id, token_id, expires_at)  # does not raise
    assert matching_store.family_is_active(family_id) is True
