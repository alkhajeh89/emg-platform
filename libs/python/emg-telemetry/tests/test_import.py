import io
import json
import logging

from emg_telemetry import get_correlation_id, get_logger, set_correlation_id


def test_correlation_id_roundtrip():
    cid = set_correlation_id()
    assert get_correlation_id() == cid


def test_logger_emits_json_with_schema_fields():
    log = get_logger("test-module")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(log.handlers[0].formatter)
    log.handlers = [handler]

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
