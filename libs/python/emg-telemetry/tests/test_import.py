import io
import json
import logging

from emg_telemetry import get_correlation_id, get_logger, set_correlation_id


def test_correlation_id_roundtrip():
    cid = set_correlation_id()
    assert get_correlation_id() == cid


def test_invalid_or_oversized_correlation_id_is_replaced():
    for untrusted in ("has space", "line\nbreak", "x" * 129):
        cid = set_correlation_id(untrusted)
        assert cid != untrusted
        assert len(cid) <= 128


def test_logger_emits_json_with_schema_fields():
    log = get_logger("test-module")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(log.logger.handlers[0].formatter)
    log.logger.handlers = [handler]

    extra = {
        "actor": "tester",
        "module": "test-module",
        "action": "unit_test",
        "outcome": "success",
    }
    log.info("unit test event", extra=extra)
    payload = json.loads(stream.getvalue())
    assert payload["message"] == "unit test event"
    assert payload["actor"] == "tester"
    assert payload["module"] == "test-module"
    assert payload["outcome"] == "success"
    assert "correlation_id" in payload


def test_logger_extra_keys_do_not_collide_with_logrecord_reserved_names():
    """Regression test: extra={"module": ...} previously crashed with
    `KeyError: Attempt to overwrite 'module' in LogRecord` because "module"
    is a reserved LogRecord attribute. get_logger() must accept the plain
    ADR-015 schema field names without raising."""
    log = get_logger("regression-module")
    # Must not raise.
    log.info(
        "regression check",
        extra={"actor": "a", "module": "m", "action": "act", "outcome": "success"},
    )
