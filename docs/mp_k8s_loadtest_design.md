# 부하테스트 통합 보고서

> 문서 상태: **부하테스트 정본**
>
> 테스트 기간: 2026-07-19~2026-07-21
>
> 범위: 초기 병목 탐색, 백엔드 개선, 동일 조건 재검증, 로그인 포함 전체 서비스 검증, 인프라 튜닝 인계
>
> 관련 작업: 진단 이슈 [#186](https://github.com/happyInit/food-budget-app/issues/186) · 구현 PR [#193](https://github.com/happyInit/food-budget-app/pull/193)

이 문서는 다음 문서를 통합하고 대체한다.

- `qa-load-test-backend-handoff.md`
- `qa-load-test-backend-retest-results.md`
- `qa-load-test-final-confirmation.md`
- `perf-loadtest-fixes.md`
- `perf-infra-handoff.md`

수치와 원인 판단이 충돌할 때는 **동일 조건 재검증과 실제 런타임 메트릭으로 확인한 후속 결과**를 우선한다.

---

## 1. 최종 요약

1. 초기 혼합 테스트는 약 **200 VUser부터 처리량이 정체**됐다. VM CPU는 약 18%로 여유가 있었지만 Price 현재가·핫딜 요청이 8~20초까지 지연됐다.
2. Price의 공통 가격 View를 Materialized View로 전환하고 Redis 읽기 캐시를 추가한 후, Price 200VU 평균 응답시간이 **1,407ms에서 4.48ms로 99.7% 감소**했다.
3. Login은 bcrypt 오프로드와 account CPU 상향 후 원본 조건인 30VU에서 **3,493ms에서 497.38ms로 약 86% 감소**했다. 다만 100VU 이상 동시 로그인에서는 account CPU가 2코어 한도의 약 98%에 도달해 여전히 포화됐다.
4. 로그인을 제외한 혼합 300VU는 평균 응답시간 **593.80ms→5.05ms**, TPS **342.97→1,437.58**로 개선됐다.
5. 로그인을 제외한 피크 500VU는 평균 응답시간 **1,130.40ms→75.81ms**, TPS **339.79→1,668.78**로 개선됐다.
6. 로그인까지 VUser당 1회 포함한 전체 서비스 테스트에서는 Account 지연이 MealPlan과 Chat으로 전파됐다. 500VU에서 Account 예산조회 최대 응답시간은 14,112ms, MealPlan cart는 8,120ms였다.
7. Kafka 딜 1,000건과 Price 400VU 읽기를 동시에 실행해도 consumer lag와 오류가 발생하지 않았다. 현재 규모에서 Kafka·Redis 튜닝이 필요하다는 증거는 없었다.

### 최종 우선순위

| 우선순위 | 대상 | 최종 판정 |
|---|---|---|
| P0 | Account | 동시 로그인 시 bcrypt CPU 포화. 현실적인 동시 로그인 목표를 정한 뒤 rate limiting 또는 수평 확장 검토 |
| P1 | MealPlan | Account 장애 전파가 주 지연 원인. DB 풀 `max_size=10` 하드코딩 문제도 별도 존재 |
| P1 | Chat | Account 장애 전파가 존재. `ILIKE '%word%'` 미인덱스·미계측 검색도 별도 개선 필요 |
| 완료 | Price | 물질화 뷰·Redis 캐시 적용 후 동일 조건 재검증 통과 |
| P2 | Recipebook·Pantry·Notify | 연속 최대 부하에서 CPU 한계가 있으나 일반 혼합 트래픽에서는 안정 |
| 관찰 | Recipe | 200VU까지 처리량 증가, 오류 없음 |
| 관찰 | Kafka·Redis | 1,000건 쓰기와 400VU 읽기 동시 조건에서 이상 없음 |

---

## 2. 테스트 환경과 판정 원칙

| 구분 | 값 |
|---|---|
| 대상 Gateway | `http://192.168.0.9` |
| 부하 도구 | nGrinder `3.5.9-p1` |
| 애플리케이션 | Docker Compose 기반 `fb-app-ai` VM |
| 관측 | Grafana·Prometheus·Loki·Tempo |
| 앱 VM | 6 vCPU · 3.8GiB RAM, 컨테이너 11개 이상 |
| PostgreSQL | `max_connections=100` 기준 |

관찰 지표:

- nGrinder: VUser, TPS, Peak TPS, 평균 응답시간, 요청 수, 오류 수
- Prometheus: VM·컨테이너 CPU/메모리, throttling, PG 연결 상태
- Tempo: 서비스·DB·Elasticsearch Span, P50·P95·P99
- Loki: 오류 로그와 timeout
- Kafka·Redis: consumer lag, 처리 성공 수, 메모리, `evicted_keys`

포화는 다음을 함께 보고 판정했다.

1. VUser가 증가해도 TPS가 거의 증가하지 않음
2. 응답시간과 timeout이 증가
3. CPU throttling, DB 풀 또는 내부 대기 증가
4. 테스트 종료 후 회복 지연

개선 전후 비교에는 같은 VUser·스크립트·실행시간을 사용했다.

### 측정 방법 정정

크로스서비스 호출에서 Tempo Trace 전체 길이는 클라이언트가 포기한 뒤 서버가 계속 처리한 시간까지 포함할 수 있다. 따라서 사용자 응답시간의 최종 판정은 nGrinder 원본 응답시간을 사용하고 Tempo는 병목 위치와 percentile 보조 증거로 사용했다.

---

## 3. 초기 병목 탐색

### 서비스별 단독 결과

| 서비스 | 조건 | 초기 결과 | 판정 |
|---|---:|---|---|
| Login | 30VU | 평균 3,493ms, 오류 약 1.4% | bcrypt·CPU 병목 후보 |
| MealPlan | 100VU | 평균 2,314ms | DB 풀·집계 경로 후보 |
| Price | 200VU | 58.2 TPS, 평균 1,407ms | 150VU 이후 포화 |
| Chat | 200VU | 41.1 TPS, 평균 1,812ms | 150VU 이후 포화 |
| Pantry | 200VU | 약 313 TPS, 평균 628ms | CPU limit 기반 한계 |
| Notify | 200VU | 약 295 TPS, 평균 674ms | CPU limit 기반 한계 |
| Recipe | 200VU | 84 TPS, 평균 354ms, 오류 0 | 안정 |

### 초기 혼합 결과

| VUser | 요청 수 | 오류율 | 평균 응답시간 | TPS | VM 최대 CPU |
|---:|---:|---:|---:|---:|---:|
| 100 | 36,081 | 0% | 96.66ms | 321.68 | 17.73% |
| 200 | 37,932 | 0% | 348.63ms | 338.32 | 18.11% |
| 300 | 38,116 | 0.0105% | 593.80ms | 342.97 | 18.39% |

200→300VU에서 VUser는 50% 증가했지만 TPS는 약 1.4%만 증가하고 평균 응답시간은 약 70% 증가했다. Price 현재가와 핫딜은 각각 약 8.6초로 확인됐다.

### 초기 피크 결과

| VUser | 요청 수 | 오류율 | 평균 응답시간 | TPS |
|---:|---:|---:|---:|---:|
| 50 | 40,951 | 0% | 6.25ms | 237.83 |
| 100 | 95,871 | 0% | 103.07ms | 329.10 |
| 300 | 96,788 | 0.007% | 675.60ms | 331.13 |
| 500 | 58,514 | 0.044% | 1,130.40ms | 339.79 |

Price 요청은 후반에 19~20초까지 지연됐다.

---

## 4. 적용한 개선

### Account

- bcrypt 해싱·검증을 `asyncio.to_thread`로 오프로드
- account CPU `0.75→2.0`, 메모리 512MiB
- signup 직후 login 401 race 수정
- bcrypt 보안 비용 인자는 유지

### DB 풀 설정

account·price·chat·notify의 PostgreSQL 풀 min/max를 환경변수로 조정할 수 있게 변경했다. MealPlan의 `max_size=10` 하드코딩은 남아 있다.

### MealPlan

- 요청마다 만들던 `httpx.AsyncClient`를 lifespan 공유 클라이언트로 변경
- 독립적인 Pantry·Account·DB 호출 병렬화
- keep-alive 연결 재사용

### Chat

- Elasticsearch 요청 timeout
- PostgreSQL statement timeout
- 검색 소스별 실패 격리와 graceful degradation

### Price·MealPlan 가격 View

`retail_unit_price`가 요청마다 가격 시계열의 윈도우 함수와 상품명 정규식을 다시 계산하던 문제를 해결하기 위해 Materialized View로 전환했다.

| 항목 | 결과 |
|---|---|
| 데이터 | 4,290행 |
| 현재가 조회 | 약 1.5ms |
| MealPlan 비교 View | 362행, 약 4.2ms |
| 갱신 | `REFRESH MATERIALIZED VIEW CONCURRENTLY` 정상 |

크롤 완료 후 `refresh_price_matview.py`가 View를 갱신한다.

### Price Redis 캐시

- 현재가: `price:current:{item_id}`, TTL 300초
- 핫딜: `price:hotdeals:{limit}`, TTL 120초
- Redis 장애 시 DB로 우회
- 크롤 후 캐시 무효화

### Notify

- 기본 50건, 최대 200건의 `limit`
- `(user_id, created_at DESC)` 인덱스

---

## 5. 동일 조건 재검증

### Price — 해결

| 구분 | VUser | TPS | 평균 응답시간 | 오류 |
|---|---:|---:|---:|---:|
| 개선 전 | 200 | 58.2 | 1,407ms | 0 |
| 개선 후 | 200 | 94.98 | 4.48ms | 0 |

- P50 1ms, P95 2ms, P99 6ms
- Price CPU 최대 18.7%

### Login — 30VU 해결, 고동시성 CPU 포화 잔존

| VUser | 성공 | 오류 | 평균 응답시간 | TPS |
|---:|---:|---:|---:|---:|
| 30 | 415 | 8 | 497.38ms | 7.97 |
| 50 | 427 | 0 | 2,972.16ms | 8.37 |
| 100 | 17 | 528 | 5,663.0ms | 0.33 |
| 200 | 25 | 1,045 | 5,348.2ms | 0.49 |

100VU 구간에서 account CPU 최대는 195.8%였지만 PG active 연결은 0이었다. 따라서 초기의 Login DB 풀 병목 추정은 폐기하고, 확인된 병목을 bcrypt CPU 포화로 정정했다.

### MealPlan — 부분 해결

| VUser | TPS | 평균 응답시간 | 오류 |
|---:|---:|---:|---:|
| 50 | 116.96 | 427.33ms | 0 |
| 100 | 114.89 | 879.47ms | 0 |
| 150 | 111.49 | 1,326.45ms | 15 |
| 200 | 105.76 | 1,887.05ms | 0 |

50VU 이후 TPS가 증가하지 않고 응답시간만 증가했다. 자체 DB 풀 문제와 Account API 장애 전파 문제를 구분해야 한다.

### Chat — 별도 검색 병목

| 구분 | VUser | TPS | 평균 응답시간 | 오류 |
|---|---:|---:|---:|---:|
| 개선 전 | 150 | 38.7 | 623ms | 0 |
| 재검증 | 150 | 32.7 | 1,364.94ms | 0 |

`PgRecipeNameSource`의 `ILIKE '%단어%'`는 일반 B-tree 인덱스를 사용할 수 없다. `pg_trgm`+GIN 검토와 `postgres.recipe_name` Span 추가가 필요하다.

### Recipebook — 낮은 우선순위

| VUser | TPS | 평균 응답시간 | 오류 |
|---:|---:|---:|---:|
| 30 | 302.72 | 98.95ms | 0 |
| 100 | 303.41 | 328.77ms | 0 |
| 200 | 301.48 | 661.44ms | 0 |

200VU P95 261ms, P99 539ms였고 CPU는 최대 68.1%로 0.75코어 한도에 근접했다. 혼합 트래픽에서는 병목이 아니었다.

---

## 6. 개선 후 혼합·피크

이 절의 스크립트는 측정 구간에서 로그인을 제외하고 사전 발급 토큰을 사용했다.

### 혼합 300VU

| 구분 | 요청 수 | 오류율 | 평균 응답시간 | TPS | Peak TPS |
|---|---:|---:|---:|---:|---:|
| 개선 전 | 38,116 | 0.0105% | 593.80ms | 342.97 | 553 |
| 개선 후 | 420,066 | 0.00048% | 5.05ms | 1,437.58 | 1,805 |

### 피크 500VU

| 구분 | 요청 수 | 오류율 | 평균 응답시간 | TPS | Peak TPS |
|---|---:|---:|---:|---:|---:|
| 개선 전 | 58,514 | 0.044% | 1,130.40ms | 339.79 | 744 |
| 개선 후 | 487,602 | 0.0023% | 75.81ms | 1,668.78 | 2,165 |

이 결과는 Price 개선 효과와 로그인 이후 평상시 트래픽 성능을 보여주지만 동시 로그인 병목은 포함하지 않는다.

---

## 7. 로그인 포함 전체 서비스 최종 확인

실행 조건:

- `full-service-journey.groovy`
- VUser당 로그인 1회, 측정 포함
- Recipe·Price·Recipebook·Account·Pantry·MealPlan·Notify·Chat
- 단계별 5분, 25→50→100→200→300→500VU
- OCR은 실비용 때문에 제외

| VU | 성공 | 오류 | 오류율 |
|---:|---:|---:|---:|
| 25 | 28,839 | 121 | 0.42% |
| 50 | 49,934 | 297 | 0.59% |
| 100 | 71,113 | 792 | 1.10% |
| 200 | 112,326 | 1,816 | 1.59% |
| 300 | 137,084 | 2,791 | 2.00% |
| 500 | 166,022 | 5,016 | 2.94% |

### Account와 장애 전파

| VU | Account 예산조회 최대 | Account CPU 최대 |
|---:|---:|---:|
| 100 | 1,941ms | 30.0% |
| 200 | 6,428ms | 58.3% |
| 300 | 13,309ms | 103.6% |
| 500 | 14,112ms | 175.6% |

MealPlan:

| VU | cart 최대 | expense-summary 최대 |
|---:|---:|---:|
| 100 | 121ms | 111ms |
| 200 | 866ms | 284ms |
| 300 | 4,219ms | 1,168ms |
| 500 | 8,120ms | 4,098ms |

Account의 사용자 조회 DB Span은 느린 사례에서도 약 68ms였다. bcrypt를 스레드로 분리해도 총 CPU 계산량은 남기 때문에 동시 로그인이 증가하면 2코어 안에서 작업이 대기한다.

MealPlan은 Account 예산 API를 기다리며, Chat은 Account 제외재료 API를 호출한다. 따라서 동시 로그인 CPU 포화가 Account의 다른 API를 밀어내고 그 지연이 MealPlan과 Chat으로 전파된다.

---

## 8. Kafka·Redis 핫딜 검증

| 배치 | Produce | Consume | Lag | 처리시간 |
|---:|---:|---:|---:|---:|
| 100 | 100 | 100 | 0 복귀 | 5초 미만 |
| 500 | 500 | 누적 600 | 0 복귀 | 4초 미만 |
| 1,000 | 1,000 | 누적 1,600 | 0 복귀 | 4초 미만 |

Kafka 딜 1,000건과 Price 핫딜 조회 400VU를 동시에 실행한 결과:

| 지표 | 결과 |
|---|---:|
| TPS | 199.03 |
| 평균 응답시간 | 4.28ms |
| 오류 | 0 |
| Kafka lag | 0 |
| Redis 메모리 | 2.64MiB/256MiB |
| `evicted_keys` | 0 |

현재 규모에서는 튜닝하지 않는다. 실제 딜 건수를 측정하고 Redis `evicted_keys` 알림을 설정한다. 테스트에서 생성한 `TEST-` 합성 데이터는 별도 정리가 필요하다.

---

## 9. 인프라 튜닝 원칙

당시 상태:

| 항목 | 값 |
|---|---|
| 앱 VM | 6 vCPU · 3.8GiB RAM |
| 앱 컨테이너 | 11개 이상 |
| 공통 CPU limit | 대부분 0.75코어 |
| uvicorn worker | 서비스당 1 |
| 앱 DB 풀 합계 | 약 60 |
| PG 연결 | 피크 약 68/100 |
| OTEL 샘플링 | 당시 100% |

연결 예산:

```text
Σ(서비스별 worker 수 × worker별 pool max)
+ 파이프라인 연결
+ exporter 연결
+ 운영 여유
≤ PostgreSQL max_connections
```

적용 원칙:

1. 모든 서비스의 worker·CPU·풀을 일괄 상향하지 않는다.
2. 실제 병목이 확인된 서비스만 조정한다.
3. 앱 풀을 늘릴 때 PostgreSQL 전체 연결 예산을 함께 계산한다.
4. worker를 늘리면 worker별 pool을 나눠 총 연결 수를 유지한다.
5. OTEL 샘플링은 운영 0.1을 기본으로 하고 집중 분석 시에만 일시 상향한다.
6. 단일 VM의 한계는 K8s replica와 HPA를 이용한 수평 확장으로 넘긴다.

초기의 구체적인 풀·`max_connections` 일괄 상향 숫자는 현재 운영 권고로 사용하지 않는다. Price는 쿼리·캐시 개선으로 해결됐고 Login은 DB가 아닌 CPU 병목으로 확인됐기 때문이다.

---

## 10. 최종 조치 계획

### P0: Account

1. DAU 500 가정에서 현실적인 동시 로그인 목표를 정한다.
2. 더 높은 동시 로그인이 필요하면 rate limiting·계정 잠금·account 수평 확장을 검토한다.
3. bcrypt 비용 인자 하향은 개선안으로 사용하지 않는다.
4. 결정된 현실적 피크로 재시험한다.

### P1: 장애 전파 차단

- MealPlan→Account timeout, 예산 캐시, 서킷브레이커 검토
- Chat→Account timeout과 fallback 계측
- timeout을 별도 metric으로 기록

### P1: 자체 병목

- MealPlan DB 풀 크기 환경변수화
- Chat `ILIKE '%word%'` 검색에 `pg_trgm`+GIN 검토
- `PgRecipeNameSource` Span 추가

### P2: 예방 관측

- Redis `evicted_keys` 알림
- 실제 딜 건수 측정
- DB pool checkout 대기시간 계측
- 컨테이너 CPU throttling과 Login 지표 분리

---

## 11. 재검증 기준과 한계

제안 목표:

| 서비스 유형 | 제안 P95 |
|---|---:|
| 단순 조회 | 500ms 이하 |
| 검색·집계 | 1초 이하 |
| Login | 1초 이하 |
| Chat | 2초 이하 |
| 공통 오류율 | 1% 미만 |

필수 기록:

- 스크립트와 커밋 SHA
- VUser, process/thread, duration, think time
- 로그인 포함 여부와 호출 수
- TPS, P50, P95, P99, 오류율, timeout
- VM·컨테이너 CPU·메모리·throttling
- PG pool 사용량·checkout 대기·active connections
- Kafka lag와 Redis eviction
- 느린 Trace와 클라이언트 응답시간
- 테스트 종료 후 회복 시간

한계:

1. VUser 비율은 운영 로그가 아니라 탐색용 가설이다.
2. nGrinder 요약 응답시간은 평균이며 P95가 아니다.
3. 로그인 제외와 로그인 포함 테스트는 서로 다른 트래픽 패턴이다.
4. Tempo Trace 길이는 클라이언트 timeout 이후의 서버 처리까지 포함할 수 있다.
5. Kafka·Redis는 1,000건·400VU까지 확인했을 뿐 최대 한계를 찾은 것은 아니다.
6. OCR은 실비용 때문에 제외했다.
7. K8s 수평 확장 효과는 아직 측정하지 않았다.

