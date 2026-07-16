"""구조화 로그가 공통 규격과 민감정보 제외 원칙을 지키는지 검증."""
from __future__ import annotations

import json
import logging

from app.observability import JsonFormatter


def _record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="chat",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="dependency failed",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emits_required_and_allowed_fields():
    formatter = JsonFormatter(service="chat", environment="test")
    payload = json.loads(
        formatter.format(
            _record(
                event="dependency_timeout",
                dependency="elasticsearch",
                error_type="TimeoutError",
                retryable=True,
            )
        )
    )

    assert payload["level"] == "ERROR"
    assert payload["service"] == "chat"
    assert payload["environment"] == "test"
    assert payload["event"] == "dependency_timeout"
    assert payload["message"] == "dependency failed"
    assert payload["dependency"] == "elasticsearch"
    assert payload["error_type"] == "TimeoutError"
    assert payload["retryable"] is True
    assert payload["timestamp"].endswith("Z")


def test_json_formatter_omits_unapproved_extra_and_empty_trace_fields():
    formatter = JsonFormatter(service="chat", environment="test")
    payload = json.loads(
        formatter.format(
            _record(
                event="request_failed",
                password="must-not-leak",
                user_id="user-123",
                trace_id="",
            )
        )
    )

    assert "password" not in payload
    assert "user_id" not in payload
    assert "trace_id" not in payload
