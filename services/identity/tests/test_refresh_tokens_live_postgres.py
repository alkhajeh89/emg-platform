from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
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
            FROM identity_refresh_token_families
            WHERE family_hash = %s OR family_hash = %s
            """,
            (family_id, first_token_id),
        )
        assert cursor.fetchall() == []
        cursor.execute(
            """
            SELECT token_hash
            FROM identity_refresh_tokens
            WHERE token_hash = %s OR token_hash = %s
            """,
            (first_token_id, next_token_id),
        )
        assert cursor.fetchall() == []
