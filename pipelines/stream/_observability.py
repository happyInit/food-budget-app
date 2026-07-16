"""Kafka 스트림 처리기의 공통 구조화 로그 설정."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any


_OPTIONAL_FIELDS = (
    "trace_id",
    "span_id",
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
)


def _json_value(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class JsonFormatter(logging.Formatter):
    """허용 목록 밖의 Kafka payload·식별자·비밀값은 직렬화하지 않는다."""

    def __init__(self, *, environment: str) -> None:
        super().__init__()
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "service": "data-pipeline",
            "environment": self._environment,
            "event": getattr(record, "event", "application_log"),
            "message": record.getMessage(),
        }
        for field in _OPTIONAL_FIELDS:
            value = getattr(record, field, None)
            if value is not None and value != "":
                payload[field] = _json_value(value)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def get_pipeline_logger(component: str) -> logging.Logger:
    """컴포넌트별 로거를 만들되 JSON의 service 값은 data-pipeline으로 통일한다."""
    formatter = JsonFormatter(environment=os.getenv("ENVIRONMENT", "development"))
    logger = logging.getLogger(f"data-pipeline.{component}")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
    logger.propagate = False
    return logger
