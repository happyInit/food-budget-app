"""서비스 로그를 공통 규격의 한 줄 JSON으로 출력한다."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any


_OPTIONAL_FIELDS = (
    "trace_id",
    "span_id",
    "request_id",
    "method",
    "route",
    "status_code",
    "duration_ms",
    "dependency",
    "operation",
    "attempt",
    "error_type",
    "error_code",
    "retryable",
    "component",
    "source",
    "topic",
    "consumer_group",
    "result",
    "record_count",
    "release",
    "generator_type",
)


def _active_trace_ids() -> dict[str, str]:
    """OTel 미설치·비활성 상태에서는 trace 필드를 생략한다."""
    try:
        from opentelemetry import trace
    except ImportError:
        return {}

    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return {}
    return {
        "trace_id": format(context.trace_id, "032x"),
        "span_id": format(context.span_id, "016x"),
    }


def _json_value(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class JsonFormatter(logging.Formatter):
    """필수 필드와 허용 목록에 있는 extra만 직렬화한다."""

    def __init__(self, *, service: str, environment: str) -> None:
        super().__init__()
        self._service = service
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "service": self._service,
            "environment": self._environment,
            "event": getattr(record, "event", "application_log"),
            "message": record.getMessage(),
        }

        trace_fields = _active_trace_ids()
        for field in _OPTIONAL_FIELDS:
            value = getattr(record, field, trace_fields.get(field))
            if value is not None and value != "":
                payload[field] = _json_value(value)

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_service_logger(*, service: str) -> logging.Logger:
    """환경변수로 서비스 로거를 구성하고 Uvicorn 오류 로그도 JSON으로 맞춘다."""
    environment = os.getenv("ENVIRONMENT", "development")
    level = os.getenv("LOG_LEVEL", "INFO")
    formatter = JsonFormatter(service=service, environment=environment)
    logger = logging.getLogger(service)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    for logger_name in ("uvicorn", "uvicorn.error"):
        for uvicorn_handler in logging.getLogger(logger_name).handlers:
            uvicorn_handler.setFormatter(formatter)
    logging.getLogger("uvicorn.access").disabled = True
    return logger
