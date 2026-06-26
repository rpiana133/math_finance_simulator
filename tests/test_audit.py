import json
import logging

from main import _audit


def test_audit_emits_info_log(caplog):
    caplog.set_level(logging.INFO)
    _audit("TEST_EVENT", "user@example.com", {"key": "val"})
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "INFO"


def test_audit_json_has_all_fields(caplog):
    caplog.set_level(logging.INFO)
    _audit("TEST_EVENT", "user@example.com", {"key": "val"})
    parsed = json.loads(caplog.records[0].getMessage())
    assert parsed["event"] == "TEST_EVENT"
    assert parsed["user"] == "user@example.com"
    assert "time" in parsed
    assert "ip" in parsed
    assert parsed["details"] == {"key": "val"}


def test_audit_without_details(caplog):
    caplog.set_level(logging.INFO)
    _audit("NO_DETAILS", "user@example.com")
    parsed = json.loads(caplog.records[0].getMessage())
    assert parsed["details"] == {}


def test_audit_custom_ip(caplog):
    caplog.set_level(logging.INFO)
    _audit("CUSTOM_IP", "user@example.com", ip="203.0.113.42")
    parsed = json.loads(caplog.records[0].getMessage())
    assert parsed["ip"] == "203.0.113.42"
