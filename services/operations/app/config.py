from __future__ import annotations

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
    pghost: str = "192.168.0.8"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""
    pg_pool_min: int = 1
    pg_pool_max: int = 10
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

    @property
    def analyzer_config(self) -> AnalyzerConfig:
        return AnalyzerConfig()
