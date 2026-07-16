# Observability 계측 규격 v1

> 상태: 1단계 규격 확정 문서  
> 범위: 로그·메트릭·분산 트레이스의 이름과 상호 연결 규칙  
> 관련 문서: [`monitoring-ops.md`](./monitoring-ops.md), [`design.md`](./design.md)  
> 작성일: 2026-07-16

이 문서는 대시보드 쿼리와 애플리케이션 계측 코드가 서로 다른 이름을 사용해
`No data`가 발생하는 일을 막기 위한 공통 계약이다. 이 문서 자체는 애플리케이션
동작을 변경하지 않는다. 실제 계측은 각 변경 전에 영향 파일과 방식을 별도로
검토한 후 적용한다.

---

## 1. 운영 조사 원칙

관측 데이터는 다음 순서로 사용한다.

```text
메트릭: 문제가 있는가?
  → 트레이스: 어느 서비스·의존성·처리 단계가 느리거나 실패했는가?
    → 로그: 구체적인 예외·재시도·폴백·입력 상태는 무엇인가?
```

- 메트릭은 대시보드와 알림의 기본 신호로 사용한다.
- 로그는 모든 서비스에서 중앙 수집하되, 대시보드 패널은 필요한 위치에만 둔다.
- 트레이스는 모든 FastAPI 서비스에 최소 자동 계측하고, 수동 Span은 중요 경로에만 추가한다.
- 전체 원문 로그와 정상 트레이스 조사는 Grafana Explore에서 수행한다.
- 동일 요청은 `trace_id`로 로그와 트레이스를 연결한다.

---

## 2. 서비스 이름 규칙

`service`, OpenTelemetry `service.name`, 대시보드 `$service` 값은 동일한 소문자
케밥 표기 값을 사용한다. 컨테이너에 임의 접미사가 붙더라도 `service.name`은
변하지 않아야 한다.

현재 FastAPI 서비스의 표준 이름은 다음과 같다.

| 코드 경로 | 표준 `service` / `service.name` |
|---|---|
| `services/account` | `account` |
| `services/chat` | `chat` |
| `services/mealplan` | `mealplan` |
| `services/notify` | `notify` |
| `services/pantry` | `pantry` |
| `services/price` | `price` |
| `services/recipe` | `recipe` |
| `services/recipebook` | `recipebook` |
| `pipelines/stream` | `data-pipeline` |

파이프라인은 장기 실행 프로세스 또는 배치 작업 단위를 `component`로 구분한다.
현재 표준 값은 `retail-refiner`, `deal-notifier`, `recipe-refiner`, `deal-pruner`와
각 poller 작업명이다. 새 이름은 코드·Prometheus·로그 쿼리에서 동일하게 사용한다.

환경 값은 배포 설정에서 주입하고 코드에 하드코딩하지 않는다. 허용 값은
`local`, `development`, `staging`, `production`이다.

---

## 3. 구조화 JSON 로그 규격

애플리케이션 로그는 한 줄에 JSON 객체 하나를 stdout/stderr로 출력한다.
호스트 cron poller 로그도 Loki 수집을 적용할 때 같은 형식을 목표로 한다.

### 3.1 필수 필드

| 필드 | 형식 | 설명 |
|---|---|---|
| `timestamp` | UTC RFC3339 문자열 | 이벤트 발생 시각 |
| `level` | 문자열 | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `service` | 문자열 | §2의 표준 서비스 이름 |
| `environment` | 문자열 | 실행 환경 |
| `event` | snake_case 문자열 | 검색과 집계를 위한 안정적인 이벤트 이름 |
| `message` | 문자열 | 사람이 읽는 짧은 설명. 동적 값을 과도하게 포함하지 않음 |

### 3.2 요청 상관관계 필드

| 필드 | 조건 | 설명 |
|---|---|---|
| `trace_id` | 유효한 Trace가 있을 때 | 32자리 소문자 hex |
| `span_id` | 유효한 Span이 있을 때 | 16자리 소문자 hex |
| `request_id` | 요청 ID를 별도로 운용할 때 | 외부 노출용 요청 식별자. 메트릭·Loki 라벨 금지 |

Trace가 없는 시작 로그나 배치 로그에는 `trace_id`를 빈 문자열로 만들지 않고
필드 자체를 생략한다.

### 3.3 조건부 필드

| 영역 | 필드 |
|---|---|
| HTTP | `method`, `route`, `status_code`, `duration_ms` |
| 의존성 | `dependency`, `operation`, `duration_ms`, `attempt` |
| 오류 | `error_type`, `error_code`, `retryable` |
| 파이프라인 | `component`, `source`, `topic`, `consumer_group`, `result`, `record_count` |
| 배포 | `release` |

- `route`는 `/recipes/{recipe_id}` 같은 라우트 템플릿을 사용하고 실제 URL을 넣지 않는다.
- `error_type`은 예외 클래스 또는 안정적인 오류 분류다.
- 스택 트레이스는 `ERROR` 이상에서만 기록하고 중복 출력하지 않는다.
- 오류 메시지 원문에 민감정보가 섞일 수 있으면 정제한 `error_code`를 우선 사용한다.

### 3.4 예시

```json
{"timestamp":"2026-07-16T03:00:00Z","level":"ERROR","service":"chat","environment":"production","event":"dependency_timeout","message":"recipe search timed out","trace_id":"4f7a9e1f8d3c4b2a9114d61db6cd3210","span_id":"6b7a8c9d0e1f2345","dependency":"elasticsearch","operation":"recipe.search","duration_ms":1502,"error_type":"TimeoutError","retryable":true}
```

---

## 4. 이벤트 이름과 로그 레벨

이벤트 이름은 문장 대신 `snake_case`의 안정적인 분류값을 사용한다. 메시지가
바뀌어도 `event`는 대시보드 쿼리와 알림 호환성을 위해 유지한다.

### 4.1 공통 이벤트

```text
application_log
service_started
service_stopped
service_start_failed
request_failed
dependency_timeout
dependency_unavailable
dependency_recovered
database_query_failed
response_validation_failed
unexpected_exception
```

### 4.2 Chat 이벤트

```text
chat_input_rejected
chat_extraction_failed
chat_search_source_failed
chat_search_empty
chat_unanswered
chat_fallback_used
chat_response_validation_failed
```

### 4.3 파이프라인 이벤트

```text
poller_started
poller_succeeded
poller_failed
poller_skipped
poller_metrics_unavailable
crawler_blocked
crawler_succeeded
kafka_consume_failed
kafka_produce_failed
kafka_produce_succeeded
sink_write_failed
pipeline_record_rejected
```

### 4.4 보안 이벤트

```text
authentication_failed
authorization_denied
token_invalid
rate_limit_exceeded
privileged_action
security_log_delivery_failed
```

### 4.5 로그 레벨 기준

| 레벨 | 기준 |
|---|---|
| `DEBUG` | 개발 환경의 상세 진단. 운영 기본 비활성화 |
| `INFO` | 시작·종료·배치 성공 등 중요한 정상 이벤트 |
| `WARNING` | 재시도, 폴백, 일부 소스 실패 등 성능 저하 상태 |
| `ERROR` | 요청·작업 실패 또는 데이터 저장 실패 |
| `CRITICAL` | 서비스 시작 불가, 데이터 무결성 위험, 보안 로그 전달 중단 |

정상 HTTP 요청을 건마다 `INFO`로 중복 기록하지 않는다. 요청량·상태코드·지연은
Prometheus HTTP 메트릭을 우선 사용한다.

---

## 5. 민감정보와 금지 데이터

다음 값은 로그와 Span attribute에 원문으로 기록하지 않는다.

- 비밀번호, JWT, 세션 토큰, API Key, Slack Webhook
- 이메일, 전화번호, 주소, 카드번호와 영수증 원본 개인정보
- 전체 사용자 질문, 전체 Chat prompt·response
- 전체 Kafka message payload
- SQL parameter와 DB 연결 문자열의 비밀번호
- HTTP `Authorization`, `Cookie`, `Set-Cookie` 헤더

문제 분석에 값이 필요하면 허용 목록 기반의 분류값, 길이, 개수 또는 복구할 수
없는 해시로 대체한다. 해시도 사용자를 장기간 추적하는 목적으로 사용하지 않는다.

---

## 6. 라벨과 카디널리티 규칙

### 6.1 Prometheus 라벨

허용되는 저카디널리티 값:

```text
service, environment, method, route_template, status_code,
dependency, component, source, topic, consumer_group, result
```

금지되는 값:

```text
trace_id, span_id, request_id, user_id, session_id,
recipe_id, product_id, 실제 URL, 오류 메시지, Kafka offset
```

### 6.2 Loki 스트림 라벨

현재 Alloy가 부여하는 스트림 라벨은 `host`, `container`, `project`다.
`service`는 구조화 로그 JSON 본문 필드이며 현재 스트림 라벨이 아니다.

따라서 현재 LogQL은 실제 스트림 라벨로 범위를 선택한 뒤 JSON을 파싱한다.

```logql
{host=~".+"}
| json
| __error__=""
| event=~"authentication_failed|authorization_denied|token_invalid|rate_limit_exceeded|privileged_action"
```

`trace_id`, `span_id`, `request_id`, 사용자·도메인 식별자는 Loki 스트림 라벨로
승격하지 않는다. 필요할 때 JSON 본문을 파싱해 검색한다.

---

## 7. OpenTelemetry Trace 규격

### 7.1 전송 경로

현재 Docker/VM 규모에서는 SDK가 Tempo로 직접 전송한다.

```text
FastAPI OpenTelemetry SDK
  → OTLP HTTP http://192.168.0.11:4318
    → Tempo
```

Tempo 주소와 프로토콜은 환경변수로 주입하고 애플리케이션 코드에 하드코딩하지 않는다.

```env
OTEL_SERVICE_NAME=chat
OTEL_EXPORTER_OTLP_ENDPOINT=http://192.168.0.11:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

Alloy OTLP 중계는 중앙 샘플링·필터링이 필요해질 때 도입하는 후속 선택 사항이다.

### 7.2 Resource attribute

최소 Resource attribute:

```text
service.name
service.version
deployment.environment.name
```

`service.name`은 §2의 이름을 사용한다. 컨테이너 ID나 인스턴스 주소를
`service.name`에 포함하지 않는다.

### 7.3 자동 계측 범위

모든 FastAPI 서비스에 다음 범위를 우선 적용한다.

- 들어오는 HTTP server 요청
- 나가는 HTTP client 요청
- PostgreSQL·Redis·Elasticsearch 호출
- W3C `traceparent` Context 전달

Kafka Producer·Consumer는 후속 단계에서 message header로 Trace Context를 전달한다.

### 7.4 수동 Span 이름

수동 Span은 `<도메인>.<단계>` 형태의 낮은 카디널리티 이름을 사용한다.
사용자 값, URL, 재료명, 레시피 ID를 Span 이름에 포함하지 않는다.

Chat 우선 Span:

```text
chat.request
├─ chat.input.check
├─ chat.extract
├─ chat.search
│  ├─ elasticsearch.recipe
│  ├─ postgres.price
│  └─ postgres.nutrition
├─ chat.context.build
├─ chat.generate
└─ chat.response.build
```

`chat.generate`는 구현체 이름으로 바꾸지 않는다. 생성 방식은
`generator.type=template` 같은 저카디널리티 attribute로 구분한다.

MealPlan 수동 Span은 실제 처리 흐름을 코드 담당자와 확인한 후 별도 승인으로 확정한다.

### 7.5 오류와 샘플링

- 처리 실패 Span은 status를 `ERROR`로 설정하고 정제된 예외 정보를 기록한다.
- 예상 가능한 4xx를 모두 Trace 오류로 간주하지 않는다.
- 초기 검증 환경에서는 모든 Trace를 수집할 수 있다.
- 트래픽과 저장량이 증가하면 parent-based ratio sampling을 적용한다.
- 샘플링 비율은 코드가 아니라 배포 환경변수로 관리한다.

---

## 8. 메트릭 이름 규칙

기존에 적용된 라이브러리·파이프라인 메트릭 이름을 대시보드 기준으로 사용한다.

```text
http_requests_total
http_request_duration_seconds
http_requests_inprogress

fb_poller_last_run_success
fb_poller_last_success_timestamp_seconds
fb_pipeline_records_total
fb_pipeline_processing_duration_seconds
fb_pipeline_sink_writes_total
fb_pipeline_last_success_timestamp_seconds
fb_pipeline_item_matches_total
fb_pipeline_deals_pruned_total
fb_pipeline_active_deals
```

새 메트릭은 다음 규칙을 따른다.

- 누적 횟수는 `_total` Counter
- 시간은 `_seconds` 단위 Histogram 또는 Gauge
- 크기는 `_bytes`
- 비율을 메트릭에 직접 저장하기보다 Counter로 수집하고 PromQL에서 계산
- 사용자·도메인 객체 ID를 라벨로 사용하지 않음

---

## 9. Grafana 연결 규칙

대시보드는 다음 연결 흐름을 제공한다.

```text
메트릭 패널
  → 동일 시간 범위의 Slow/Error Trace
    → trace_id가 포함된 Loki 로그
      → Loki/Tempo Explore 상세 조회
```

명시적 로그 패널:

1. `01 Service Detail / Recent Error Logs`
2. `02 Data Pipeline / Recent Pipeline Errors`
3. `Detail - Chat Pipeline & Quality / Recent Chat Error Logs`
4. `06 Security Overview / Privileged & Audit Activity`

명시적 Trace 패널:

1. `01 Service Detail / Recent Slow/Error Traces`
2. `Detail - Chat Pipeline & Quality / Recent Slow/Error Traces`

Grafana 데이터소스 UID는 기존 고정값 `prometheus`, `loki`, `tempo`를 사용한다.

---

## 10. 적용 전 완료 조건

각 계측 변경은 다음 조건을 확인한 뒤 대시보드에 연결한다.

- [ ] 로그 한 줄이 유효한 JSON 객체다.
- [ ] 필수 필드와 표준 서비스 이름이 들어 있다.
- [ ] 민감정보가 기록되지 않는다.
- [ ] 오류 로그의 `trace_id`로 Tempo Trace를 찾을 수 있다.
- [ ] 서비스 간 호출에서 Trace가 끊기지 않는다.
- [ ] 실제 라벨과 쿼리를 Explore에서 먼저 검증했다.
- [ ] 메트릭·Loki 라벨에 고카디널리티 값이 없다.
- [ ] 계측 실패가 애플리케이션 요청 처리를 실패시키지 않는다.

---

## 11. 다음 구현 경계

이 문서 이후의 구현은 다음 순서로 진행한다.

1. `monitoring_agents`에 poller 파일 로그 수집 추가
2. 애플리케이션 JSON 로그 적용 — `services/`, `pipelines/`, `crawler/`, `deploy/` 수정 전 승인
3. FastAPI OTel SDK와 Tempo 직접 전송 적용 — `services/` 수정 전 승인
4. 모든 서비스 자동 계측 — `services/` 수정 전 승인
5. Chat·MealPlan 수동 Span — 비즈니스 코드 수정 전 승인
6. 배포·Explore 검증 후 대시보드 JSON 작성

애플리케이션·데이터 파이프라인 코드와 실제 서버는 사전 설명과 승인 없이 수정하거나
배포하지 않는다.
