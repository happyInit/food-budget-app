"""상주 Kafka consumer용 Prometheus 메트릭.

각 consumer는 별도 컨테이너이므로 같은 메트릭 이름을 사용하고 component 라벨로
구분한다. 포트는 compose가 METRICS_PORT 환경변수로 주입한다.
"""
import os

from prometheus_client import Counter, Gauge, Histogram, start_http_server


RECORDS = Counter(
    "fb_pipeline_records_total",
    "Kafka consumer가 처리한 레코드 수",
    ("component", "result"),
)
PROCESSING_SECONDS = Histogram(
    "fb_pipeline_processing_duration_seconds",
    "레코드 또는 정리 작업 처리시간",
    ("component",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
SINK_WRITES = Counter(
    "fb_pipeline_sink_writes_total",
    "consumer의 저장소 쓰기 결과",
    ("component", "sink", "result"),
)
LAST_SUCCESS = Gauge(
    "fb_pipeline_last_success_timestamp_seconds",
    "component가 마지막으로 처리를 성공한 Unix 시각",
    ("component",),
)
ITEM_MATCHES = Counter(
    "fb_pipeline_item_matches_total",
    "consumer의 item_id 매칭 결과",
    ("component", "result"),
)
DEALS_PRUNED = Counter(
    "fb_pipeline_deals_pruned_total",
    "deal-pruner가 제거한 만료 딜 수",
    ("component",),
)
ACTIVE_DEALS = Gauge(
    "fb_pipeline_active_deals",
    "Redis에 남아 있는 활성 딜 수",
    ("component",),
)


def start_metrics_server(component: str) -> int:
    """METRICS_PORT가 있으면 HTTP 메트릭 서버를 시작하고 포트를 반환한다."""
    port = int(os.environ.get("METRICS_PORT", "0"))
    if port:
        start_http_server(port)
        print(f"metrics {component} listening on :{port}")
    return port
