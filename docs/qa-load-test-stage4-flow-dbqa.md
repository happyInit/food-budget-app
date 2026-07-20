# 4단계(전체 흐름) 재검증 — DB 병목 우선순위 분석

> 작성일: 2026-07-20
>
> 목적: DB담당자 요청("특정 서비스 단독이 아니라 전체 흐름 부하에서, 가장 먼저 지연되는 서비스 중 원인이 DB 쿼리인 것만") 대응. 방법·실행·nGrinder 원본 결과·판정 근거를 전부 기록한다.

## 1. DB담당자 요청 원문 (요약)

> 왠만하면 특정 서비스에 대한 부하보단 전체 흐름에 대한 부하이고, 가장 먼저 지연이 발생하는 서비스들이 뭔지, 근데 이제 그 원인이 DB 쿼리인 경우에만 저한테 주세요. 그 외에 주시면 안 됩니다. 오늘까지 보내주세요.

이전에 보낸 `db-tuning-request.md`는 **단독(서비스별) 테스트** 결과였고, Login처럼 DB 원인이 아닌 것도 섞여 있었다. 이번엔 요청대로 **전체 흐름(혼합 시나리오)** 기준으로 다시 뽑았다.

## 2. 시나리오 — 무엇을 돌렸나

### 2.1 스크립트: `mixed-capacity-journey.groovy`

테스트 시작 시(`@BeforeProcess`) 로그인 토큰을 한 번만 발급받고(측정 안 됨), 이후 매 반복마다 **가상 사용자가 4개 행동 패턴 중 하나를 랜덤하게 골라 수행**한다. 고정 그룹 분할이 아니라 매 반복마다 다시 확률을 굴리는 방식이다.

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
| recipeJourney | 50% | `/api/recipes?q=...`(recipe 검색) → `/api/recipes/6100`(recipe 상세) → `/api/prices/35`(price) → `/api/recipes/book`(recipebook) |
| planningJourney | 25% | `/api/users/budget`(account) → `/api/pantry/items`(pantry) → `/api/mealplan/cart`(mealplan) → `/api/expenses/summary`(mealplan) |
| dealJourney | 15% | `/api/prices/hotdeals`(price) |
| chatJourney | 10% | `/api/mealplan/assistant/chat`(chat) |

**측정되는 서비스 7개**: Recipe, Price, Recipebook, Pantry, MealPlan, Notify, Chat. (Account는 로그인 1회만·측정 제외, OCR은 이 시나리오에 아예 없음 — 이미지 업로드 방식이 달라 별도 테스트 대상)

### 2.2 실행 조건

| 구분 | 300VU | 500VU |
|---|---|---|
| nGrinder 테스트명 | `mixed-flow-300vu-dbqa` (id=86) | `mixed-flow-500vu-dbqa` (id=87) |
| duration | 5분 | 5분 |
| ramp-up | init 20, step 20, 3초 간격 | init 20, step 20, 3초 간격 |
| 시작~종료 | 2026-07-20 (start=1784540456026, finish=1784540756991) | 2026-07-20 (start=1784540777884, finish=1784541078040) |

**중요**: 백엔드가 요청받은 MealPlan·Chat 수정을 아직 반영하기 **전** 상태에서 돌렸다. 다 고친 뒤 결과가 아니라, "지금 여러 문제 중 실제로 뭐가 제일 급한지" 우선순위를 뽑기 위한 의도적 선택이다(§6 참고).

## 3. nGrinder 원본 결과 (집계)

| 구분 | 300VU | 500VU |
|---|---:|---:|
| 총 요청 수(tests) | 412,765 | 436,342 |
| 오류 | 0 | 2 |
| 평균 응답시간(meanTestTime) | 8.74ms | 106.88ms |
| TPS | 1,412.7 | 1,498.54 |

집계 평균만 보면 둘 다 멀쩡해 보이지만, **평균은 함정이다** — 서비스별로 쪼개보면 완전히 다른 그림이 나온다(§4).

## 4. 서비스별 분해 (Tempo 트레이스, 각 500건 샘플)

| 서비스 | 300VU P50/P95/P99(ms) | 500VU P50/P95/P99(ms) | 300→500 추이 |
|---|---|---|---|
| **Chat** | 50 / 183 / **222** | 93 / 449 / **541** | 계속 최악, 더 악화 |
| **MealPlan** | 9 / 50 / 86 | 58 / 479 / **537** | 300→500에서 급격히 악화 |
| **Pantry** | 6 / 35 / 73 | 10 / 458 / **503** | 300→500에서 급격히 악화(신규 발견) |
| Recipe | 5 / 82 / 108 | 4 / 47 / 98 | 안정 |
| Recipebook | 2 / 10 / 68 | 2 / 7 / 12 | 안정 |
| Price | 1 / 3 / 6 | 1 / 2 / 4 | 완전 안정 |
| Notify | 2 / 6 / 7 | 2 / 6 / 12 | 완전 안정 |

**300VU 기준**: Chat이 압도적 1위(P99 222ms), 나머지는 전부 100ms 이하로 양호.

**500VU 기준**: Chat·MealPlan·Pantry **셋이 동시에 500ms대로 폭발**. Recipe·Recipebook·Price·Notify는 500VU에서도 여전히 안정적(오히려 일부는 300VU보다 나음 — 캐시 워밍 등 영향으로 추정).

## 5. 원인 확인 — CPU인가 DB인가 (3층 판정 기준 적용)

Chat·MealPlan·Pantry 3개에 대해 500VU 구간의 컨테이너 CPU와 PostgreSQL 커넥션 상태를 직접 확인했다.

| 서비스 | CPU 최대(한도 75%) | 판정 |
|---|---:|---|
| Chat | 49.9%(평균 41.1%) | CPU 여유 있음 → **DB 쿼리가 원인** |
| MealPlan | 63.1%(평균 51.9%) | CPU 여유 있음 → **DB 커넥션 풀 고갈이 원인** |
| Pantry | 28.7%(평균 23.9%) | CPU 전혀 안 바쁨 → **DB 커넥션 풀 고갈이 원인** |

**PostgreSQL 커넥션 상태(500VU 구간, `foodbudget` DB 전체)**:

| state | 최대 | 평균 |
|---|---:|---:|
| idle | 66 | 59.0 |
| **idle in transaction** | **14** | 8.2 |
| active | 0 | 0 |

`idle in transaction`(트랜잭션 잡은 채 대기)이 최대 14개까지 쌓인 것도 확인 — 커넥션이 반납 안 되고 정체되는 실제 증거다.

### 5.1 왜 Pantry가 이번에 처음 터졌는가

Pantry는 원본 문서·이번 세션 어떤 단독 테스트에서도 문제된 적 없다(원본 §4.6: 약 310 TPS 한계는 있었지만 우선순위 낮음으로 판정). 이번 혼합 테스트에서만 드러난 이유는 두 가지가 겹쳤기 때문으로 추정된다.

1. **절대 동시 요청 수 증가**: 시나리오 비중(planningJourney 25%)은 300VU·500VU 둘 다 동일하지만, VUser 총량이 늘면서 실제 동시 인원(300VU 기준 약 75명 → 500VU 기준 약 125명)이 늘었다. Pantry 풀은 `services/pantry/app/db.py`에 `max_size=10`으로 하드코딩돼 있어(MealPlan과 동일 패턴), 늘어난 동시 인원을 못 받아낸다.
2. **같은 물리 DB 서버를 여러 서비스가 나눠 쓰는 구조**: Pantry 자체 풀(10개)과 MealPlan 풀(10개)은 숫자상 서로 안 겹치지만, 결국 **같은 PostgreSQL 서버 인스턴스 하나**에 다 붙는다. Chat의 느린 쿼리와 MealPlan의 자체 풀 부족이 겹치면 DB 서버 전체가 바빠지고, Pantry의 원래 빠른 쿼리도 처리가 밀려 커넥션 반납이 늦어진다 — 결과적으로 Pantry 자체 풀도 평소보다 빨리 바닥난다.

두 요인의 정확한 기여 비율까지는 이번 데이터로 분리하지 못했다 — 필요하면 Pantry 단독 500VU 재현 테스트로 추가 검증 가능하다.

## 6. 결론 — DB담당자에게 보낼 3건

원본 진단이던 "이벤트 루프 블로킹"이나 CPU 문제(Login)는 이번 리스트에서 전부 제외했다. 아래 3개만 **전체 흐름에서 실제로 드러났고 원인이 DB로 확인된** 항목이다.

| 서비스 | 원인 | 근거 |
|---|---|---|
| **Chat** | 미인덱스 쿼리(`PgRecipeNameSource`의 ILIKE 풀스캔) | 트레이스 91% 미계측 구간 확인(기존), CPU 49.9%로 여유(신규) |
| **MealPlan** | DB 커넥션 풀 고갈(`max_size=10` 하드코딩) | 단독 테스트에서 이미 확인(기존), 혼합 500VU에서 P99 537ms로 재확인(신규) |
| **Pantry** | DB 커넥션 풀 고갈(`max_size=10` 하드코딩) | **이번 혼합 테스트에서 처음 발견** — 단독 테스트에선 문제없었음 |

우선순위: **300VU 기준으로는 Chat이 압도적 1순위**, 500VU까지 가면 MealPlan·Pantry도 거의 동급으로 심각해진다. 셋 다 오늘 중 전달 대상이다.

## 7. 안전 확인

두 테스트 내내 `fb-app-ai` VM CPU를 10초 간격으로 모니터링했다. 300VU 최대 57.6%, 500VU 최대 61.7%로 위험 수준(80%)에 전혀 근접하지 않았다. 서버 중단·재시작 없이 정상 종료됐다.

## 8. 참고

- 기존 단독(서비스별) 재검증 결과: `docs/qa-load-test-backend-retest-results.md`
- 기존 DB 요청서(단독 테스트 기반, 이번 문서로 대체): `docs/db-tuning-request.md`
