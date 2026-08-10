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
    # ── Kafka 전달 판정 (#558) ────────────────────────────────────────────────
    # 🔴 이 허용목록에 없는 키는 **조용히 버려진다.** 실측(2026-08-09): 09037b4 가 남긴
    #    `failed_categories`·`min_expected`·`category_code`·`reason` 은 지금 로그에 하나도
    #    안 찍히고 있었다 — 관측을 붙였다고 믿는 자리가 사실은 비어 있었다.
    #    payload·식별자·비밀값을 막는다는 이 목록의 취지는 유지한다(전부 계수·코드값이다).
    "delivered_count",     # 브로커가 ack 한 수 = 진짜 성과
    "failed_count",        # delivery report 가 실패로 보고한 수(영구 실패)
    "remaining_count",     # flush 후에도 큐에 남은 수
    "reason",              # 실패 분류 키워드(자유 문장 금지)
    "category_code",       # 컬리 카테고리 코드(숫자)
    "failed_categories",   # 실패 카테고리 코드 목록
    "min_expected",        # 총합 하한(상수)
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
