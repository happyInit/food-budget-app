"""Chat 서비스 구조화 로그 공통 설정.

허용 목록에 있는 필드만 JSON으로 내보내 임의의 객체·요청 본문·비밀값이
실수로 로그에 직렬화되는 것을 막는다. OpenTelemetry가 설치된 뒤에는 현재
Span의 trace_id/span_id를 자동으로 덧붙이고, 설치 전에는 해당 필드를 생략한다.
"""
from __future__ import annotations

import json
import logging
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
    """OTel 미설치·비활성 상태에서는 빈 값을 반환한다."""
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
    """공통 필드와 명시적으로 허용한 extra만 한 줄 JSON으로 출력한다."""

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


def configure_service_logger(*, service: str, environment: str, level: str) -> logging.Logger:
    """서비스·Uvicorn 오류 로그를 JSON으로 통일하고 중복 access log를 끈다."""
    formatter = JsonFormatter(service=service, environment=environment)
    logger = logging.getLogger(service)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    # Uvicorn은 앱 import 전에 handler를 구성한다. 기존 handler의 출력 형식만
    # 교체하고, 정상 요청은 Prometheus HTTP 메트릭과 중복되므로 access log를 끈다.
    for logger_name in ("uvicorn", "uvicorn.error"):
        for uvicorn_handler in logging.getLogger(logger_name).handlers:
            uvicorn_handler.setFormatter(formatter)
    logging.getLogger("uvicorn.access").disabled = True
    return logger
