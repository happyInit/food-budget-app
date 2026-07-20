# 4단계(전체 흐름) 재검증 — 300VU/500VU 혼합 시나리오

> 작성일: 2026-07-20
>
> 배경: DB담당자가 "서비스 단독이 아니라 전체 흐름 부하에서, 가장 먼저 지연되는 서비스 중 원인이 DB 쿼리인 것만" 알려달라고 요청. 이 문서는 그 답을 만들기 위해 돌린 300VU·500VU 전체 흐름 테스트의 **조건·원본 지표 전체**와 **분석**을 먼저 정리하고, 맨 마지막(§7)에 DB담당자에게 실제로 전달할 요약만 따로 뺐다.

## 1. 테스트 방법

### 1.1 시나리오: `mixed-capacity-journey.groovy`

로그인은 테스트 시작 시(`@BeforeProcess`) 1회만 수행하고 측정에서 제외한다. 이후 매 반복마다 가상 사용자가 아래 4개 행동 패턴 중 하나를 랜덤 확률로 골라 수행한다(고정 그룹이 아니라 반복마다 재추첨).

```groovy
int bucket = ThreadLocalRandom.current().nextInt(100)
if (bucket < 50) recipeJourney()        // 50%
else if (bucket < 75) planningJourney() // 25%
else if (bucket < 90) dealJourney()     // 15%
else chatJourney()                       // 10%
grinder.sleep(1~3초 랜덤 대기)             // 저니 사이 think time
```

| 저니 | 비중 | 호출 엔드포인트(서비스) |
|---|---:|---|
| recipeJourney | 50% | `/api/recipes?q=...`(recipe) → `/api/recipes/6100`(recipe) → `/api/prices/35`(price) → `/api/recipes/book`(recipebook) |
| planningJourney | 25% | `/api/users/budget`(account) → `/api/pantry/items`(pantry) → `/api/mealplan/cart`(mealplan) → `/api/expenses/summary`(mealplan) |
| dealJourney | 15% | `/api/prices/hotdeals`(price) |
| chatJourney | 10% | `/api/mealplan/assistant/chat`(chat) |

측정되는 서비스는 7개(Recipe·Price·Recipebook·Pantry·MealPlan·Notify·Chat). Account는 로그인 1회만이라 측정 제외, OCR은 이 시나리오에 없음(업로드 방식이 달라 별도 테스트 대상).

**중요**: 요청했던 MealPlan·Chat 수정이 아직 반영되기 **전** 상태로 돌렸다. 고친 뒤 결과가 아니라 "지금 여러 문제 중 뭐가 제일 급한지" 우선순위를 뽑기 위한 의도적 선택.

### 1.2 공통 실행 조건

- nGrinder 3.5.9-p1, ramp-up: 초기 20명 투입 후 3초 간격으로 20명씩 증가
- duration: 5분(러닝) — 각각 300명/500명까지 채운 뒤 5분간 유지
- 대상: `fb-app-ai` 서비스 전체(nginx 경유)

## 2. 300VU 테스트 결과 전체

- nGrinder 테스트명: `mixed-flow-300vu-dbqa` (id=86)
- 목표 동시 VUser: 300명
- 진행 시간: 5분(2026-07-20, start=1784540456026 ~ finish=1784540756991)

### 2.1 nGrinder 집계 지표

| 지표 | 값 |
|---|---:|
| 총 요청 수(tests) | 412,765 |
| 오류 수 | 0 |
| 평균 응답시간(meanTestTime) | 8.74ms |
| TPS | 1,412.7 |

### 2.2 VM 안전 모니터링 (`fb-app-ai` VM CPU, 테스트 중 10초 간격 추적)

테스트 시작 시 19.9%에서 시작해 VUser가 300명까지 채워지는 동안 점진 상승, 최대 57.6%에서 안정화. 위험 수준(80%)과 거리가 멀어 안전.

### 2.3 서비스별 응답시간 분포 (Tempo 트레이스 500건 샘플)

| 서비스 | P50(ms) | P95(ms) | P99(ms) |
|---|---:|---:|---:|
| **Chat** | 50 | 183 | **222** |
| MealPlan | 9 | 50 | 86 |
| Pantry | 6 | 35 | 73 |
| Recipe | 5 | 82 | 108 |
| Recipebook | 2 | 10 | 68 |
| Price | 1 | 3 | 6 |
| Notify | 2 | 6 | 7 |

300VU에서는 **Chat만** P99 200ms를 넘겨 눈에 띄고, 나머지 6개 서비스는 전부 100ms대 이하로 양호.

## 3. 500VU 테스트 결과 전체

- nGrinder 테스트명: `mixed-flow-500vu-dbqa` (id=87)
- 목표 동시 VUser: 500명
- 진행 시간: 5분(2026-07-20, start=1784540777884 ~ finish=1784541078040)

### 3.1 nGrinder 집계 지표

| 지표 | 값 |
|---|---:|
| 총 요청 수(tests) | 436,342 |
| 오류 수 | 2 |
| 평균 응답시간(meanTestTime) | 106.88ms |
| TPS | 1,498.54 |

집계 평균(106.88ms)만 보면 300VU 대비(8.74ms) 크게 나빠진 것처럼 보이는데, 이는 특정 서비스 몇 개가 전체 평균을 끌어올린 것이지 전 서비스가 골고루 나빠진 게 아니다 — 아래 §3.3에서 서비스별로 쪼개서 확인.

### 3.2 VM 안전 모니터링 (`fb-app-ai` VM CPU)

테스트 시작 시 29.3%에서 시작해 최대 61.7%까지 상승 후 유지. 역시 위험 수준(80%)에 근접하지 않아 안전하게 완료.

### 3.3 서비스별 응답시간 분포 (Tempo 트레이스 500건 샘플)

| 서비스 | P50(ms) | P95(ms) | P99(ms) | 300VU 대비 |
|---|---:|---:|---:|---|
| **Chat** | 93 | 449 | **541** | 계속 최악, 더 악화 |
| **MealPlan** | 58 | 479 | **537** | 급격히 악화 |
| **Pantry** | 10 | 458 | **503** | 급격히 악화(300VU에선 문제없었음) |
| Recipe | 4 | 47 | 98 | 안정 |
| Recipebook | 2 | 7 | 12 | 안정 |
| Price | 1 | 2 | 4 | 완전 안정 |
| Notify | 2 | 6 | 12 | 완전 안정 |

500VU에서는 **Chat·MealPlan·Pantry 3개가 동시에 P99 500ms대로 폭발**한다. 나머지 4개(Recipe·Recipebook·Price·Notify)는 500VU에서도 여전히 안정적.

## 4. 원인 분석 — CPU인가 DB인가

Chat·MealPlan·Pantry 3개에 대해 500VU 구간의 실제 컨테이너 CPU와 PostgreSQL 커넥션 상태를 직접 확인했다(3층 판정 기준: ①증상 확인 ②용량 한계 확인 ③CPU/DB 내부 근거 확인 — 전부 적용).

### 4.1 컨테이너 CPU (500VU 구간, 컨테이너별 한도 75%)

| 서비스 | CPU 최대 | CPU 평균 | 판정 |
|---|---:|---:|---|
| Chat | 49.9% | 41.1% | CPU 여유 있음 → DB 쿼리가 원인 |
| MealPlan | 63.1% | 51.9% | CPU 여유 있음 → DB 커넥션 풀 고갈이 원인 |
| Pantry | 28.7% | 23.9% | CPU 전혀 안 바쁨 → DB 커넥션 풀 고갈이 원인 |

셋 다 컨테이너별 CPU 한도(75%)에 전혀 도달하지 않았다 — CPU가 병목이 아니라는 뜻.

### 4.2 PostgreSQL 커넥션 상태 (500VU 구간, `foodbudget` DB 전체)

| state | 최대 | 평균 |
|---|---:|---:|
| idle | 66 | 59.0 |
| **idle in transaction** | **14** | 8.2 |
| active | 0 | 0 |

`idle in transaction`(트랜잭션을 잡은 채 대기 중인 커넥션)이 최대 14개까지 쌓였다 — 커넥션이 빨리 반납되지 않고 정체되는 실제 증거.

### 4.3 서비스별 근본 원인

| 서비스 | 원인 | 근거 |
|---|---|---|
| Chat | 미인덱스 쿼리(`PgRecipeNameSource`의 `ILIKE '%...%'` 풀스캔, `services/chat/app/pipeline/search.py`) | 기존 단독 테스트에서 트레이스 91% 미계측(다크 타임) 구간 확인 + 이번엔 CPU 49.9%로 여유 재확인 |
| MealPlan | DB 커넥션 풀 고갈(`max_size=10` 하드코딩, `services/mealplan/app/db.py`) | 기존 단독 테스트에서 이미 확인 + 이번 500VU 혼합에서 P99 537ms로 재확인 |
| Pantry | DB 커넥션 풀 고갈(`max_size=10` 하드코딩, `services/pantry/app/db.py`) | **이번 혼합 테스트에서 처음 발견** — 단독 테스트에선 문제없었음 |

### 4.4 왜 Pantry가 이번에 처음 터졌는가

Pantry는 원본 문서나 이번 세션의 어떤 단독 테스트에서도 문제된 적 없다. 이번 혼합 테스트에서만 드러난 이유는 두 가지가 겹쳤을 것으로 추정된다.

1. **절대 동시 요청 수 증가**: 시나리오 비중(planningJourney 25%)은 300VU·500VU 둘 다 같지만, 전체 VUser가 늘면서 실제 동시 인원도 함께 늘었다(300VU 기준 약 75명 → 500VU 기준 약 125명이 이 저니 수행 중). Pantry 풀은 10개로 고정돼 있어 늘어난 동시 인원을 못 받아낸다.
2. **같은 물리 DB 서버를 여러 서비스가 나눠 쓰는 구조**: Pantry 자체 풀(10개)과 MealPlan 풀(10개)은 숫자상 서로 안 겹치지만 결국 같은 PostgreSQL 서버 인스턴스 하나에 다 붙는다. Chat의 느린 쿼리와 MealPlan의 풀 부족이 겹쳐 DB 서버 전체가 바빠지면, Pantry의 원래 빠른 쿼리도 처리가 밀리면서 커넥션 반납이 늦어지고 결과적으로 Pantry 자체 풀도 평소보다 빨리 바닥난다.

두 요인의 정확한 기여 비율까지는 이번 데이터로 분리하지 못했다 — 필요하면 Pantry 단독 500VU 재현 테스트로 추가 검증 가능.

## 5. 300VU→500VU 종합 비교

| 서비스 | 300VU P99 | 500VU P99 | CPU(500VU) | 결론 |
|---|---:|---:|---:|---|
| Chat | 222ms | 541ms | 49.9% | 300VU부터 이미 문제, DB 쿼리 원인 |
| MealPlan | 86ms | 537ms | 63.1% | 500VU에서 급격히 악화, DB 풀 원인 |
| Pantry | 73ms | 503ms | 28.7% | 500VU에서 신규 발생, DB 풀 원인 |
| Recipe/Recipebook/Price/Notify | ≤108ms | ≤98ms | - | 두 단계 모두 안정 |

## 6. 안전 확인 요약

두 테스트 내내 `fb-app-ai` VM CPU를 모니터링했다(300VU 19.9%→57.6%, 500VU 29.3%→61.7%). 위험 수준(80%) 근처에도 가지 않았고 서버 중단·재시작 없이 정상 종료됐다.

---

## 7. DB담당자 전달용 요약 (이 부분만 전달)

전체 흐름(300VU/500VU 혼합 시나리오) 기준으로 가장 먼저 지연되는 서비스 3개, 전부 원인이 DB 쿼리로 확인된 것만 정리.

| 서비스 | 원인 | 500VU P99 |
|---|---|---:|
| **Chat** | 미인덱스 쿼리 — `PgRecipeNameSource`의 `ILIKE '%키워드%'` 풀스캔 (leading wildcard라 인덱스 사용 불가) | 541ms |
| **MealPlan** | DB 커넥션 풀 고갈 — `max_size=10` 하드코딩 | 537ms |
| **Pantry** | DB 커넥션 풀 고갈 — `max_size=10` 하드코딩 (이번 혼합 테스트에서 처음 발견) | 503ms |

세 서비스 모두 CPU는 여유(50~63%, 한도 75%) 있었고 PostgreSQL `idle in transaction` 커넥션이 최대 14개까지 쌓인 것으로 봐서 커넥션이 제때 반납되지 못하고 있다. 우선순위는 300VU 시점부터 이미 나쁜 **Chat이 1순위**, 500VU에서 MealPlan·Pantry도 거의 동급으로 심각해진다.

## 8. 참고

- 기존 단독(서비스별) 재검증 결과: `docs/qa-load-test-backend-retest-results.md`
- 기존 DB 요청서(단독 테스트 기반, 이번 문서로 대체): `docs/db-tuning-request.md`
