"""Chat OpenTelemetry 초기화와 수동 업무 Span 헬퍼.

Trace가 비활성화됐거나 OTel 패키지가 없는 로컬 환경에서는 no-op으로 동작한다.
Exporter 장애도 BatchSpanProcessor의 백그라운드 전송 실패로 격리돼 Chat 요청을
실패시키지 않는다.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator


_configured = False
_enabled = False
_tracer: Any = None
_log = logging.getLogger("chat")


class _NoOpSpan:
    def set_attribute(self, key: str, value: Any) -> None:  # noqa: ARG002
        return None


def mark_span_error(span: Any, exc: Exception) -> None:
    """호출부가 예외를 복구하더라도 해당 업무 Span은 실패로 표시한다."""
    if not _enabled:
        return
    try:
        from opentelemetry.trace import Status, StatusCode
    except ImportError:
        return
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, type(exc).__name__))


@contextmanager
def start_span(name: str, *, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """현재 Trace의 자식 Span을 시작한다. 비활성 상태에서는 같은 API의 no-op을 반환한다."""
    if not _enabled or _tracer is None:
        yield _NoOpSpan()
        return

    clean_attributes = {
        key: value
        for key, value in (attributes or {}).items()
        if value is not None and isinstance(value, (str, bool, int, float))
    }
    with _tracer.start_as_current_span(name, attributes=clean_attributes) as span:
        yield span


def configure_tracing(
    app: Any,
    *,
    service_name: str,
    environment: str,
    endpoint: str,
    enabled: bool,
    insecure: bool,
    sample_ratio: float,
) -> bool:
    """OTLP exporter와 자동 계측을 한 번만 설정한다.

    FastAPI 요청, Psycopg3, Redis, Elasticsearch 호출은 자동 Span으로 만들고,
    업무 의미가 필요한 Chat 단계는 ``start_span``으로 별도 기록한다.
    """
    global _configured, _enabled, _tracer

    if _configured:
        return _enabled
    _configured = True

    if not enabled:
        _log.info(
            "OpenTelemetry tracing disabled",
            extra={"event": "tracing_disabled", "component": "opentelemetry"},
        )
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.elasticsearch import ElasticsearchInstrumentor
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    except ImportError as exc:
        _log.error(
            "OpenTelemetry tracing packages unavailable",
            extra={
                "event": "tracing_setup_failed",
                "component": "opentelemetry",
                "error_type": type(exc).__name__,
                "retryable": False,
            },
        )
        return False

    ratio = min(max(sample_ratio, 0.0), 1.0)
    resource = Resource.create(
        {
            "service.name": service_name,
            "deployment.environment.name": environment,
        }
    )
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(ratio)),
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=endpoint,
                insecure=insecure,
            )
        )
    )
    trace.set_tracer_provider(provider)

    # contrib Elasticsearch 계측을 명시적으로 사용한다. Elastic client의 native
    # 계측을 별도로 켜지 않아 중복 Span이 생기지 않도록 한다.
    PsycopgInstrumentor().instrument(tracer_provider=provider)
    RedisInstrumentor().instrument(tracer_provider=provider)
    ElasticsearchInstrumentor().instrument(tracer_provider=provider)
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls="health,metrics",
    )

    _tracer = trace.get_tracer("food-budget-app.chat")
    _enabled = True
    _log.info(
        "OpenTelemetry tracing configured",
        extra={
            "event": "tracing_configured",
            "component": "opentelemetry",
            "result": "enabled",
        },
    )
    return True
