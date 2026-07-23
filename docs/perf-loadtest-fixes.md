# 부하테스트 병목 개선 — 수정 내역 정리

> 관련: 진단 이슈 [#186](https://github.com/happyInit/food-budget-app/issues/186) · 구현 PR [#193](https://github.com/happyInit/food-budget-app/pull/193) (커밋 `04de7ff`)
> 인프라 튜닝 후속(코드 아님) = [`docs/perf-infra-handoff.md`](perf-infra-handoff.md)

nGrinder 부하테스트에서 **~200 VUser 부근 포화**(응답 8~20초, 타임아웃)가 관측됐다. VM CPU는 18%로 여유였지만 컨테이너 `cpus`·워커 수·**커넥션 풀** 상한에 먼저 막혔고, 그 위에 몇 가지 **코드 레벨 병목**이 겹쳐 있었다. 아래는 코드로 해결한 8건(A1~A4·B1~B4)의 **무엇을·왜·어떻게**와 반영 상태다.

---

## 요약 표

| ID | 서비스 | 문제(근원) | 수정 | 반영 상태 |
|----|--------|-----------|------|-----------|
| **A1** | account | bcrypt(동기·수십 ms)가 **이벤트 루프 블로킹** → 로그인/가입 동시성 붕괴 | `asyncio.to_thread` 오프로드 | 새 이미지 배포 필요 |
| **A2** | account·price·chat·notify | 풀 크기 하드코딩 → 부하 튜닝 불가 | 풀 min/max **env 노출** | 배포 필요(기본값 무변) |
| **A3** | mealplan | 호출마다 `httpx.AsyncClient` 새로 생성 + 크로스서비스 **직렬 왕복** | **공유 클라이언트**(keep-alive) + `asyncio.gather` 병렬화 | 배포 필요 |
| **A4** | chat | 느린 ES/PG가 커넥션 무한 점유 → 풀 고갈 / 소스 1개 장애가 전체 응답 실패 | ES·PG **타임아웃** + 소스별 **graceful degrade** | 배포 필요 |
| **B1** | price·mealplan | 공유 뷰 `retail_unit_price`(일반 VIEW)를 **조회마다 재계산**(윈도우+정규식) | **물질화 뷰(Materialized View)** + 크롤 후 REFRESH | ✅ **fb-data 라이브 적용 완료** |
| **B2** | price | 현재가·핫딜을 매번 DB 조회 | **Redis 읽기 캐시**(best-effort) | 배포 필요 |
| **B3** | (인프라) | `cpus`·워커·PG `max_connections` 상한이 근원 | **인프라 핸드오프 문서**로 정리 | 인프라 담당 협의 대기 |
| **B4** | notify | 누적 알림 **무제한 반환** + 조회 인덱스 없음 | `limit` 파라미터 + `(user_id, created_at DESC)` 인덱스 | 인덱스=배포 시 DDL |

> **핵심**: `B1`(물질화 뷰)이 Price·MealPlan 공통 병목의 **근원**이라 가장 효과가 크고, **이미 fb-data에 직접 적용**돼 재배포 없이 라이브 효과가 있다. 나머지(A1~A4·B2·B4 인덱스)는 코드/설정이라 **새 이미지 빌드·배포 시** 활성화된다.

---

## A1 — account: bcrypt 이벤트 루프 오프로드

**문제.** bcrypt 해싱/검증은 CPU 집약(수십 ms)이고 **동기**라, async 핸들러 안에서 직접 호출하면 그 시간 동안 **이벤트 루프 전체가 멈춘다**. 로그인·가입이 몰리면 다른 모든 요청이 뒤에 줄서서 지연이 폭증한다.

**수정.** [`services/account/app/routers.py`](../services/account/app/routers.py) — `asyncio.to_thread`로 스레드 오프로드:

```python
# signup
pw_hash = await asyncio.to_thread(sec.hash_password, body.password)
# login (row/해시 없으면 단락되어 실행 안 됨)
or not await asyncio.to_thread(sec.verify_password, body.password, row["password_hash"])
```

`security.py`는 **순수 동기 그대로** 유지 → 기존 DB-free 테스트 무변. (라우터에서만 오프로드)

---

## A2 — 커넥션 풀 크기를 env로 노출

**문제.** 풀 크기가 코드에 하드코딩돼, 부하 상황에 맞춰 조정하려면 재빌드가 필요했다. 요청당 여러 커넥션을 잡는 경로(예: mealplan 합계+예산 병렬)에서 **풀 고갈**이 포화를 앞당겼다.

**수정.** account·price·chat·notify의 `config.py`에 두 값 추가, `db.py`가 이를 사용:

```python
pg_pool_min: int = 1
pg_pool_max: int = 5      # account/mealplan=10, price/chat/notify=5 (기존값 그대로)
```
```python
AsyncConnectionPool(conninfo, min_size=settings.pg_pool_min, max_size=settings.pg_pool_max, ...)
```

**기본값은 현재와 동일** → 배포해도 런타임 동작 무변. 운영에서 `PG_POOL_MAX` env만 올리면 튜닝 가능(값 근거는 B3 핸드오프 문서).

---

## A3 — mealplan: 공유 HTTP 클라이언트 + 크로스서비스 병렬화

**문제.** 스키마-퍼-서비스라 mealplan은 예산·재고를 **API 호출**로 가져온다. 그런데 (1) 크로스서비스 provider가 **호출마다 `httpx.AsyncClient()`를 새로 생성**(TCP+TLS 핸드셰이크 반복, keep-alive 못 씀), (2) 서로 독립인 호출을 **직렬**로 기다렸다.

**수정.**
- [`context.py`](../services/mealplan/app/context.py) — provider들이 **생성자에서 공유 `httpx.AsyncClient`를 주입**받아 재사용. pantry의 `items`·`expiring`은 독립이라 `asyncio.gather`로 병렬 호출.
- [`main.py`](../services/mealplan/app/main.py) lifespan — 공유 클라이언트 1개 생성(`Limits(max_keepalive_connections=20, max_connections=100)`), provider들에 주입, 종료 시 `aclose()`.
- [`routers.py`](../services/mealplan/app/routers.py) — cart(재고+예산), summary(월지출+예산+절약) 등 **독립 조회를 `asyncio.gather`로 동시 실행**.

> `recommend`는 degrade 게이팅 로직 때문에 **의도적으로 병렬화 제외**(순서 의존).

---

## A4 — chat: 하위 저장소 타임아웃 + 소스별 degrade

**문제.** chat은 ES(레시피)·PG(가격·영양) 등 여러 소스를 fan-out한다. 느린 소스 하나가 커넥션을 **무한 점유**하면 풀이 고갈되고, 소스 1개 장애가 **전체 응답을 실패**시켰다.

**수정.**
- [`config.py`](../services/chat/app/config.py) — `es_request_timeout_s: float = 3.0`, `pg_statement_timeout_ms: int = 8000` 추가.
- `db.py` — PG conninfo에 `options='-c statement_timeout=...'`, ES 클라이언트에 `request_timeout=...` 적용 → 느린 쿼리가 상한에서 끊겨 커넥션 반납.
- [`pipeline/search.py`](../services/chat/app/pipeline/search.py) — 각 소스의 쿼리를 `try/except`로 감싸 실패 시 `SearchResult(available=False, reason=...)` 반환(**graceful degrade**). fan-out은 이미 `asyncio.gather` 병렬.

> 결과: 가격 소스가 죽어도 레시피·영양 결과로 응답이 나가고, 느린 쿼리가 풀을 잡아먹지 않는다.

---

## B1 — price·mealplan: `retail_unit_price` 물질화 뷰 (⭐ 근원 병목, 라이브 적용 완료)

**문제.** `retail_unit_price`는 **일반 VIEW**라 데이터를 들고 있지 않고 저장된 SQL일 뿐이다. 조회할 때마다:
- `retail_price`(가격 시계열, 16,892행) 전체에 `row_number() OVER (PARTITION BY 상품 ORDER BY crawled_at DESC)` **윈도우 함수**
- `retail_product`(4,290행)에 상품명 파싱용 **정규식 LATERAL 3개**

를 **매번 재계산**한다. 단건은 16ms지만 200+ VUser가 동시에 두드리고 풀이 5개면 재계산이 쌓여 **8~20초로 폭증**. Price·MealPlan이 이 뷰를 공유한다(Chat은 자체 쿼리라 무관).

**수정.** [`docs/prd/schema-public-data.sql`](prd/schema-public-data.sql) — SELECT 본문은 **한 글자도 안 바꾸고** 성격만 전환:
- `CREATE OR REPLACE VIEW` → **`CREATE MATERIALIZED VIEW retail_unit_price`** (결과를 디스크에 저장 → 조회는 즉시 읽기)
- `CREATE UNIQUE INDEX retail_unit_price_id_idx (id)` — `REFRESH ... CONCURRENTLY`(갱신 중 읽기 허용) 필수 조건
- `CREATE INDEX retail_unit_price_item_idx (item_id)` — 서비스 item_id 조회 가속
- 상위 `retail_item_price_compare`·`retail_item_piece_compare`는 물질화 뷰 위 일반 뷰로 유지(가벼운 GROUP BY)
- **서비스 쿼리는 이름이 같아 무변경**(투명)

**최신 유지(REFRESH 배선).** [`pipelines/ingest/refresh_price_matview.py`](../pipelines/ingest/refresh_price_matview.py) — `REFRESH MATERIALIZED VIEW CONCURRENTLY`(autocommit, 최초 1회 미populate면 일반 REFRESH 폴백, 미마이그레이션이면 skip) + 크롤 후 Price 캐시(`price:*`) best-effort flush. `load_retail.main()` 끝에서 자동 호출. 가격은 배치성(크롤 일1~2회)이라 물질화 궁합이 딱 맞는다.

**운영 tier 전환.** [`pipelines/ingest/migrate_price_matview.py`](../pipelines/ingest/migrate_price_matview.py) — `apply_schema.py`는 `DROP TABLE CASCADE`(데이터 삭제)라 운영에 재적용 불가 → **데이터 무손상 전용 멱등 마이그레이션**. SQL은 손복사 없이 `schema-public-data.sql`에서 추출(정본 1곳).

### ✅ fb-data(운영 tier) 직접 적용·검증 완료

| 항목 | 결과 |
|---|---|
| 전환 | 일반 뷰(owner=fbapp) → **물질화 뷰(relkind=m)**, 0.4초, 데이터 무손상 |
| populate | **4,290행** + 인덱스 2종 |
| price 현재가 쿼리(item_id) | **1.5ms** |
| mealplan compare 뷰 | 362행 · **4.2ms** |
| REFRESH CONCURRENTLY | 정상 |
| 멱등성(재실행) | `skipped:up_to_date` (2026-07-23 정의 기반 감지로 변경 — 종전 `skipped:already_materialized` 는 정의가 바뀌어도 skip 되는 한계가 있었다) |

> **B1은 재배포 없이 이미 라이브 효과** — 서비스가 이름으로 조회하므로 현재 실행 중인 컨테이너에 즉시 적용됨.
> **데이터 담당 후속**: 크롤 스케줄에 `refresh_price_matview.py` 등록(폴 윈도우 뒤).

---

## B2 — price: Redis 읽기 캐시 (best-effort)

**문제.** 현재가·핫딜은 배치 크롤 사이에는 값이 바뀌지 않는데도 요청마다 DB를 쳤다.

**수정.** [`services/price/app/main.py`](../services/price/app/main.py)·`db.py`·`config.py`·`requirements.txt`:
- `_cache_get`/`_cache_set` **best-effort 헬퍼** — redis 미가용/장애면 `None`(=미스)로 우회해 **엔드포인트 무손상**.
- 현재가 `GET /{item_id}` → `price:current:{item_id}`(TTL 300s), 핫딜 → `price:hotdeals:{limit}`(TTL 120s). **404는 캐시 안 함**(품목 생기면 즉시 반영).
- 캐시 무효화는 B1의 크롤 후 flush와 연동.

---

## B3 — 인프라 튜닝 (핸드오프 문서로 분리)

**문제.** 포화의 1차 원인은 코드가 아니라 **컨테이너 `cpus`·워커 수·PG `max_connections` 상한**이다(VM CPU 18%인데 컨테이너 천장에 먼저 막힘). 이 값들은 인프라 담당 영역이라 코드 PR에 섞지 않고 별도 문서로 정리했다.

**산출물.** [`docs/perf-infra-handoff.md`](perf-infra-handoff.md) — fb-app-ai 실측 스펙(6 vCPU/3.8GiB, 11+ 컨테이너, `cpus:0.75×11≈8.25` 오버서브스크립션), 제약식 `Σ(워커×풀) + 파이프라인 + 익스포터 ≤ max_connections`, 풀 상향 권고(price/chat 5→12, mealplan 10→15, notify 5→10 ≈ 총 92), PG `max_connections 100→150` + PG 메모리 2~3GiB, OTEL 샘플링 1.0→0.1, 워커 신중 증설(RAM-bound). **근본 해법은 K8s 수평 확장**이라는 점 명시.

---

## B4 — notify: limit 상한 + 조회 인덱스

**문제.** 알림함이 누적 알림을 **무제한 반환**(직렬화 비용·응답 폭증) + `(user_id, created_at)` 조회 인덱스 부재.

**수정.**
- [`queries.py`](../services/notify/app/queries.py) — `list_notifications(..., limit: int = 50)` + SQL `order by created_at desc limit %s`.
- [`routers.py`](../services/notify/app/routers.py) — `limit: int = Query(50, ge=1, le=200)`(A05 범위 검증).
- [`schema-production.sql`](prd/schema-production.sql) — `CREATE INDEX IF NOT EXISTS notification_user_created_idx ON notify.notification (user_id, created_at DESC);`
- 테스트 갱신(`params == (7, 50)`, `"limit %s" in sql`).

---

## 반영 상태 & 후속

- ✅ **라이브 적용됨(재배포 불필요)**: B1 물질화 뷰(fb-data에 직접 적용·검증).
- ⏳ **새 이미지 빌드·배포 시 활성화**: A1·A2·A3·A4·B2, B4의 코드 부분. (main에 머지 완료 — CI가 새 이미지 빌드 후 배포하면 반영)
- 📌 **DDL 적용 필요**: B4 알림 인덱스(`schema-production.sql` 재적용 or 수동 `CREATE INDEX`).
- 🤝 **인프라 담당 협의**: B3(`docs/perf-infra-handoff.md`)의 `cpus`·워커·`max_connections` 값 적용.
- 🔁 **데이터 담당**: 크롤 스케줄에 `refresh_price_matview.py` 등록.
- 📉 **재측정**: 위 반영 후 nGrinder 재실행으로 포화점 상승 확인.

### 의도적으로 후속으로 미룬 것 (테스트 seam 재작업 필요, #186 기록)
- **mealplan**: 커넥션을 HTTP 왕복 밖에서 잡기(현재는 provider 호출 동안 DB 커넥션 미점유가 이미 부분 해결됨).
- **chat**: 서비스 내 PG 커넥션 통합.
