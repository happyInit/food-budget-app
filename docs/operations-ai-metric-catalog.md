# Operations AI 이상징후 Metric Catalog

## 목적

이 문서는 Operations Prometheus Collector와 Anomaly Analyzer가 사용할 관측 지표의
입력 계약이다. 각 항목은 탐지 대상 지표, PromQL, 그룹 라벨, 위험 방향, 판정 방식,
수집 준비 상태를 정의한다.

현재는 v0 초안이다. `Ready` 항목만 Collector 1차 구현 대상으로 사용한다.
`Verify`는 Grafana 또는 Prometheus에서 실제 라벨과 시계열을 확인해야 한다.
`Gap`은 exporter, ServiceMonitor 또는 애플리케이션 계측이 추가되어야 한다.

## 운영 원칙

- 지표 그룹 라벨은 낮은 카디널리티만 사용한다. 사용자 ID, 레시피 ID, 요청 ID,
  URL Query Parameter는 사용하지 않는다.
- 숫자 시계열은 Rolling Z-score, MAD, 변화율, 연속 구간으로 판단한다.
- Pod Restart, OOMKilled는 이벤트 또는 횟수 증가 신호이므로 정규분포 기반 점수 대신
  발생 또는 증가 조건으로 판단한다.
- 정적 임계값 Alert는 Alertmanager 입력이다. 조기 이상징후 탐지를 대체하지 않는다.
- Evidence Package에 넣는 모든 지표는 Prometheus, Loki, Tempo 또는 Kubernetes에서
  원본 근거를 다시 열 수 있어야 한다.

## 수집 준비 상태

| 상태 | 의미 |
| --- | --- |
| Ready | 현재 클러스터에서 메트릭 이름과 수집 경로가 확인됨 |
| Verify | 설치된 스택상 존재해야 하지만 실제 라벨 또는 시계열 확인이 필요함 |
| Gap | 워크로드는 있으나 Prometheus 수집 경로가 확인되지 않음 |

## 1차 Metric Catalog

| ID | 영역 | 그룹 기준 | Source / PromQL | 위험 방향 | 조기 탐지 방식 | 정적 Alert | 상태 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `service_p95_latency` | Service / APM | `service` | `histogram_quantile(0.95, sum by(service, le) (rate(http_request_duration_highr_seconds_bucket{namespace="app"}[5m])))` | 증가 | 최소 요청률 이상일 때 Z-score, MAD, 변화율, 3구간 연속 | p95 SLO 임계값 초과 | Ready |
| `service_request_rate` | Service / APM | `service` | `sum by(service) (rate(http_request_duration_highr_seconds_count{namespace="app"}[5m]))` | 증가 또는 감소 | Z-score, MAD, 변화율 | 트래픽 급증 또는 급감 | Ready |
| `service_5xx_rate` | Service / APM | `service`, `status` | 응답 상태 라벨이 포함된 HTTP Count 메트릭 필요 | 증가 | Z-score, MAD, 변화율 | 5xx 오류율 임계값 초과 | Gap |
| `pod_cpu_usage` | Kubernetes | `namespace`, `pod`, `container` | `sum by(namespace, pod, container) (rate(container_cpu_usage_seconds_total{namespace=~"app|data|pipeline", container!="", container!="POD", container!="istio-proxy", image!=""}[5m]))` | 증가 | Z-score, MAD, 지속 상승 | CPU 포화 | Ready |
| `pod_memory_working_set` | Kubernetes | `namespace`, `pod`, `container` | `sum by(namespace, pod, container) (container_memory_working_set_bytes{namespace=~"app|data|pipeline", container!="", container!="POD", container!="istio-proxy", image!=""})` | 증가 | Z-score, MAD, 지속 상승 | 메모리 압박 | Ready |
| `pod_restart_increase` | Kubernetes 이벤트 | `namespace`, `pod`, `container` | `increase(kube_pod_container_status_restarts_total{namespace=~"app|data|pipeline"}[5m])` | 증가 | 횟수 증가, Z-score 미사용 | Restart Loop | Ready |
| `pod_oom_killed` | Kubernetes 이벤트 | `namespace`, `pod`, `container` | `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}` | 발생 | 발생 자체, Z-score 미사용 | OOMKilled 발생 | Ready |
| `kafka_consumer_lag` | Data Pipeline | `consumergroup`, `topic` | `sum by(consumergroup, topic) (kafka_consumergroup_lag)` | 증가 | Z-score, MAD, 양의 변화율, 연속 구간 | Lag 증가 | Ready |
| `poller_failure_count` | Data Pipeline | `poller`, `reason` | `fb_poller_last_run_failures` | 증가 | 정상 0 기준에서 변화 | 실패 횟수 0 초과 | Gap |
| `poller_last_success_age` | Data Pipeline | `poller` | `time() - fb_poller_last_success_timestamp_seconds` | 증가 | 실행 주기 보정 경과시간 | 정상 실행 주기 초과 | Gap |
| `pipeline_sink_failure_rate` | Data Pipeline | `component`, `sink` | `sum by(component, sink) (rate(fb_pipeline_sink_writes_total{result="failure"}[5m]))` | 증가 | Z-score, 연속 구간 | 실패율 0 초과 | Gap |
| `postgres_connection_ratio` | Data System | `instance` | `100 * sum(pg_stat_database_numbackends{datname!~"template.*"}) / max(pg_settings_max_connections)` | 증가 | Z-score, MAD, 지속 상승 | 연결 포화 | Gap |
| `postgres_query_latency` | Data System / Trace | `service`, `db_system` | PostgreSQL 호출 OTel Span Duration Histogram, 정확한 이름과 라벨은 확인 필요 | 증가 | Z-score, MAD, 변화율 | DB 의존성 지연 | Gap |
| `redis_memory_ratio` | Data System | `instance` | `100 * redis_memory_used_bytes / redis_memory_max_bytes` | 증가 | Z-score, MAD | 메모리 압박 | Ready |
| `elasticsearch_heap_ratio` | Data System | `cluster`, `name` | `100 * sum(elasticsearch_jvm_memory_used_bytes{area="heap"}) / sum(elasticsearch_jvm_memory_max_bytes{area="heap"})` | 증가 | Z-score, MAD | Heap 임계값 초과 | Gap |

## 현재 확인된 수집 사실

- `app/mp-app-services`는 `app` 라벨이 있는 Service의 `/metrics`를 30초마다 수집한다.
  `frontend`, `ranking-serving`은 제외되어 있다.
- Grafana에서 확인한 현재 애플리케이션 Histogram 이름은
  `http_request_duration_highr_seconds_bucket`이며 `_count`, `_sum`, `_created`
  시계열도 존재한다. `highr` 표기는 현재 계측 코드가 실제로 내보내는 이름이므로,
  코드 수정 전까지 그대로 사용한다.
- HTTP Histogram에는 현재 `service` 라벨만 확인됐다. `status`, `handler` 라벨이 없어
  5xx 오류율은 계산할 수 없다. 5xx 탐지에는 애플리케이션 HTTP 계측 보완이 필요하다.
- 현재 서비스 요청률이 0이라 p95 결과도 `NaN`으로 확인됐다. Collector는 최소 요청률을
  만족하지 않는 구간의 p95를 평가에서 제외해야 하며, 최소 요청률은 k6 부하 검증 때 확정한다.
- Kubernetes에는 kube-state-metrics, kubelet, node-exporter ServiceMonitor가 있다.
  Pod CPU, Working Set Memory, Restart, OOMKilled의 `namespace`, `pod`, `container`
  라벨과 실제 시계열을 확인했다. 애플리케이션 지표에서는 `istio-proxy` sidecar를 제외한다.
- Redis는 `data` namespace에서 ServiceMonitor 수집 경로가 확인됐다.
- Redis Memory 사용량과 최대값 메트릭도 실제 수집 중이다.
- Kafka exporter와 `retail-refiner`, `deal-notifier` Consumer Lag 시계열은 실제 수집 중이다.
- PostgreSQL `pg_up`, Elasticsearch JVM Heap, Poller 메트릭은 현재 Prometheus에서
  반환되지 않았다. 해당 항목은 exporter 또는 Pipeline 수집 경로 보완이 필요하다.

## Grafana Explore 검증 쿼리

아래 PromQL을 인클러스터 Prometheus 데이터소스에서 실행한 뒤, `Verify` 항목을
`Ready`로 변경한다.

```promql
# 애플리케이션 Histogram의 service, status, handler 라벨 확인
count by (service, status, handler) (
  http_request_duration_highr_seconds_count{namespace="app"}
)

# Kubernetes 자원 메트릭 라벨 확인
count by (namespace, pod, container) (
  container_cpu_usage_seconds_total{namespace=~"app|data|pipeline", container!=""}
)

# Pod 재시작과 OOMKilled 메트릭 확인
sum by (namespace, pod, container) (
  increase(kube_pod_container_status_restarts_total{namespace=~"app|data|pipeline"}[1h])
)
kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}

# Kafka exporter 수집 여부 확인
count by (job, instance) (kafka_brokers)
sum by (consumergroup, topic) (kafka_consumergroup_lag)

# Redis exporter 수집 여부 확인
redis_up
```

## Collector 1차 구현 범위

실제 라벨 검증이 끝난 아래 항목부터 Collector에 넣는다.

```text
service_p95_latency
service_request_rate
pod_cpu_usage
pod_memory_working_set
pod_restart_increase
pod_oom_killed
kafka_consumer_lag
redis_memory_ratio
```

5xx 오류율, Poller, PostgreSQL, Elasticsearch 지표는 수집 경로 또는 애플리케이션 계측을
보완한 뒤 추가한다.

## Collector 동작 방식

Collector는 기본 60초마다 Prometheus HTTP API를 조회한다. 숫자 시계열은 최근 120분을
60초 간격으로 가져와 Anomaly Analyzer에 전달한다. 정상 결과는 저장하지 않으며
`candidate`, `anomaly` 결과만 `operations.anomalies`에 저장한다.

- p95 지연은 같은 서비스의 최근 요청률이 최소 요청률 이상일 때만 평가한다. 유휴 구간의
  `NaN` p95를 이상으로 오판하지 않기 위함이다.
- Pod Restart와 OOMKilled는 숫자 분포 분석 대상이 아니다. 최근 5분 증가/변화가 있으면
  이벤트 이상 후보로 바로 저장한다.
- 초기 기본값은 조회 120분, 60초 간격, 최소 요청률 0.1 RPS다. 이 값은 k6 검증 결과로
  서비스 트래픽에 맞게 조정한다.

운영 적용 시에는 다음 환경 변수를 설정한다.

```text
OPERATIONS_DATABASE_ENABLED=true
OPERATIONS_COLLECTOR_ENABLED=true
OPERATIONS_PROMETHEUS_URL=http://kube-prometheus-stack-prometheus.observability.svc:9090
```

`POST /internal/collector/run`은 배포 후 수동 점검용 내부 API다. 정기 수집은
`OPERATIONS_COLLECTOR_ENABLED=true`일 때만 시작한다.

## 다음 작업

1. `Ready` 항목을 대상으로 Prometheus Collector를 구현한다.
2. p95 평가에 사용할 최소 요청률을 k6 검증 후 확정한다.
3. 5xx 오류율, Poller, PostgreSQL, Elasticsearch의 관측 공백을 보완한다.
