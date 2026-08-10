import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from emg_knowledge_graph_api.config import Settings, search_cursor_keys
from emg_knowledge_graph_api.search_cursor import InvalidSearchCursor, SearchCursorCodec
from pydantic import ValidationError

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def codec(keys=None):
    return SearchCursorCodec("active", keys or {"active": b"a" * 32}, timedelta(minutes=15))


def test_cursor_round_trip_and_confidentiality():
    token = codec().encode("tenant-a", "secret query", 7, 2, "entity-secret", 20, now=NOW)
    assert "secret query" not in token and "entity-secret" not in token
    state = codec().decode(token, "tenant-a", "secret query", now=NOW)
    assert (state.revision, state.tier, state.node_id) == (7, 2, "entity-secret")


@pytest.mark.parametrize(
    ("tenant", "query", "offset"),
    [
        ("tenant-b", "secret query", 0),
        ("tenant-a", "wrong", 0),
        ("tenant-a", "secret query", 901),
    ],
)
def test_cursor_wrong_binding_or_expiry_fails_closed(tenant, query, offset):
    token = codec().encode("tenant-a", "secret query", 7, 2, "entity", 20, now=NOW)
    with pytest.raises(InvalidSearchCursor):
        codec().decode(token, tenant, query, now=NOW + timedelta(seconds=offset))


def test_tampered_and_unknown_key_fail_closed():
    token = codec().encode("tenant-a", "q", 1, 1, "entity", 20, now=NOW)
    with pytest.raises(InvalidSearchCursor):
        codec().decode(token[:-1] + ("A" if token[-1] != "A" else "B"), "tenant-a", "q", now=NOW)
    with pytest.raises(InvalidSearchCursor):
        SearchCursorCodec("other", {"other": b"b" * 32}, timedelta(minutes=15)).decode(
            token, "tenant-a", "q", now=NOW
        )


def test_prior_key_remains_usable_during_rotation():
    old = codec().encode("tenant-a", "q", 1, 1, "entity", 20, now=NOW)
    rotated = SearchCursorCodec(
        "new", {"active": b"a" * 32, "new": b"b" * 32}, timedelta(minutes=15)
    )
    assert rotated.decode(old, "tenant-a", "q", now=NOW).revision == 1


def test_rapid_rotations_keep_every_unexpired_cursor_decryptable():
    now = datetime.now(timezone.utc)
    encoded_keys = {
        f"key-{number}": base64.b64encode(bytes([number + 1]) * 32).decode() for number in range(13)
    }
    entries = {
        "key-12": {"status": "active", "key": encoded_keys["key-12"]},
    }
    tokens = []
    for number in range(12):
        retired_at = now - timedelta(seconds=12 - number)
        entries[f"key-{number}"] = {
            "status": "retired",
            "key": encoded_keys[f"key-{number}"],
            "retired_at": retired_at.isoformat(),
            "accept_until": (retired_at + timedelta(hours=1)).isoformat(),
        }
        issuing_codec = SearchCursorCodec(
            f"key-{number}",
            {f"key-{number}": bytes([number + 1]) * 32},
            timedelta(minutes=30),
        )
        tokens.append(
            issuing_codec.encode(
                "tenant-a", "q", number + 1, 1, f"entity-{number}", 20, now=retired_at
            )
        )
    settings = Settings(
        search_cursor_active_key_id="key-12",
        search_cursor_keys_json=json.dumps(entries),
    )
    rotated = SearchCursorCodec(
        "key-12", search_cursor_keys(settings, now=now), timedelta(minutes=30)
    )
    assert [rotated.decode(token, "tenant-a", "q", now=now).revision for token in tokens] == list(
        range(1, 13)
    )


def test_unsafe_or_disabled_open_key_lifecycle_is_rejected_at_startup():
    now = datetime.now(timezone.utc)
    active = base64.b64encode(b"a" * 32).decode()
    retired = base64.b64encode(b"b" * 32).decode()
    for status, accept_delta in (
        ("retired", timedelta(minutes=30)),
        ("disabled", timedelta(hours=1)),
    ):
        entries = {
            "active": {"status": "active", "key": active},
            "prior": {
                "status": status,
                "key": retired,
                "retired_at": now.isoformat(),
                "accept_until": (now + accept_delta).isoformat(),
            },
        }
        with pytest.raises(ValidationError):
            Settings(
                search_cursor_active_key_id="active",
                search_cursor_keys_json=json.dumps(entries),
            )


def test_key_is_safely_removable_after_guaranteed_acceptance_window():
    now = datetime.now(timezone.utc)
    entries = {
        "active": {
            "status": "active",
            "key": base64.b64encode(b"a" * 32).decode(),
        },
        "prior": {
            "status": "disabled",
            "retired_at": (now - timedelta(hours=2)).isoformat(),
            "accept_until": (now - timedelta(hours=1)).isoformat(),
        },
    }
    settings = Settings(
        search_cursor_active_key_id="active",
        search_cursor_keys_json=json.dumps(entries),
    )
    assert search_cursor_keys(settings, now=now) == {"active": b"a" * 32}


def test_cursor_is_bound_to_endpoint_and_unique_nonce():
    other = SearchCursorCodec(
        "active",
        {"active": b"a" * 32},
        timedelta(minutes=15),
        endpoint_binding="POST:/another-endpoint",
    )
    token = other.encode("tenant-a", "q", 1, 1, "entity", 20, now=NOW)
    with pytest.raises(InvalidSearchCursor):
        codec().decode(token, "tenant-a", "q", now=NOW)
    first = codec().encode("tenant-a", "q", 1, 1, "entity", 20, now=NOW)
    second = codec().encode("tenant-a", "q", 1, 1, "entity", 20, now=NOW)
    assert first != second


def test_cursor_expiry_is_capped_by_representation_retirement():
    retirement = NOW + timedelta(minutes=5)
    token = codec().encode(
        "tenant-a",
        "q",
        1,
        1,
        "entity",
        20,
        now=NOW,
        representation_expires_at=retirement,
    )
    state = codec().decode(token, "tenant-a", "q", now=NOW)
    assert state.expires_at == retirement
