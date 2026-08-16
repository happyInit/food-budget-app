from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models import AnalyzerConfig


class Settings(BaseSettings):
    """Operations runtime settings.

    Database persistence is intentionally opt-in so pure calculation endpoints
    can still run locally without a PostgreSQL instance. Production must set
    ``OPERATIONS_DATABASE_ENABLED=true`` before accepting Alertmanager traffic.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    operations_database_enabled: bool = False
    pghost: str = "localhost"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""
    pg_pool_min: int = 1
    # P3: Pooler 경유 — 10 → 5. 다중화는 Pooler 가 한다(object_spec §4.5·§7.4).
    pg_pool_max: int = 5
    operations_collector_enabled: bool = False
    operations_prometheus_url: str = (
        "http://kube-prometheus-stack-prometheus.observability.svc:9090"
    )
    operations_collector_interval_seconds: int = 60
    operations_collector_lookback_minutes: int = 120
    operations_collector_step_seconds: int = 60
    # k6 검증 전 임시값이다. 실제 서비스 트래픽에 맞춰 확정한다.
    operations_min_request_rate: float = 0.1
    operations_evidence_time_window_minutes: int = 15
    # Kubernetes API 접근은 Operations 전용 ServiceAccount/RBAC가 준비된 뒤에만 켠다.
    operations_kubernetes_evidence_enabled: bool = False
    operations_kubernetes_api_url: str = "https://kubernetes.default.svc"
    operations_kubernetes_namespace: str = "app"
    operations_kubernetes_token_path: str = (
        "/var/run/secrets/kubernetes.io/serviceaccount/token"
    )
    operations_kubernetes_ca_path: str = (
        "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    )
    # Loki/Tempo 연동은 연결·저장·오탐을 확인하기 전까지 기본 비활성 상태로 둔다.
    operations_loki_evidence_enabled: bool = False
    operations_loki_url: str = "http://loki.observability.svc.cluster.local:3100"
    operations_loki_query_timeout_seconds: float = 10.0
    operations_loki_max_samples_per_pattern: int = 5
    operations_tempo_evidence_enabled: bool = False
    operations_tempo_url: str = "http://tempo.observability.svc.cluster.local:3200"
    operations_tempo_query_timeout_seconds: float = 10.0
    # AppHighP95Latency 정적 알림 임계값(1s)과 맞춘 기본값이다.
    operations_tempo_slow_trace_threshold_ms: int = 1000
    operations_tempo_max_traces: int = 20
    # AWS 자격증명과 Bedrock 호출 구현 전에는 결정론적 mock RCA만 사용한다.
    operations_rca_provider: Literal["mock", "bedrock"] = "mock"
    # 대시보드 챗봇. RCA와 별개 provider 스위치 — 하나가 bedrock이어도 다른 하나는
    # mock으로 둘 수 있다(예: RCA는 아직 자격증명 대기, 챗봇 UI만 먼저 검증).
    operations_chat_provider: Literal["mock", "bedrock"] = "mock"
    # 이름은 boto3가 인식하는 표준 AWS 환경변수와 맞춘다(로컬 access key ·
    # EC2 IAM Instance Profile 둘 다 같은 필드로 받는다).
    aws_region: str = "ap-northeast-2"
    bedrock_model_id: str = "apac.amazon.nova-micro-v1:0"
    # RAG(런북 검색). Loki/Tempo와 같은 이유로 기본 비활성 — 코퍼스가 비어 있으면
    # ingest부터 해야 검색이 의미가 있다.
    operations_rag_enabled: bool = False
    operations_embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    # RCA/챗봇 답변의 Contextual Grounding Check. 빈 문자열 = 비활성(다른 기능들과
    # 같은 opt-in 패턴) — Guardrail을 만들기 전에는 호출부가 guardrailConfig를 안 실어야
    # 안전하다. mp-operations-rca(dql8inggh3zq) v1, threshold 0.5/0.5는 실측 튜닝 전
    # 시작값 — Loki/Tempo 문턱값들과 같은 caveat.
    operations_guardrail_id: str = ""
    operations_guardrail_version: str = ""

    @property
    def analyzer_config(self) -> AnalyzerConfig:
        return AnalyzerConfig()
