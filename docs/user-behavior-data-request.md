# 유저 행동 데이터 요청서 — 개인화 레시피 랭킹(P1, LightGBM)

> **작성:** 건우 (AI 담당) · 2026-07-16
> **수신:** 데이터 담당 · 백엔드 개발자
> **목적:** P1 개인화 레시피 랭킹(LightGBM) **학습·서빙에 필요한 유저 행동 데이터**의 수집·저장 요청
> **상태:** 요청(설계 협의 필요) · 근거 `ai-spec.md §3` · **수집 동의·P0 편입 팀 승인 전제**
> **이벤트 6종 교차검증(2026-07-16):** A(기능 결정, 계측만)=VIEW·ADD_CART·NOTIF_CLICK / B(기능 미결정, 신설 결정 선행)=DISCARD·LIKE·COOKED. 상세 §2.1.

---

## 1. 배경 (왜 요청하나)

개인화 레시피 랭킹은 2단계다(`ai-spec §3`): **P0 규칙**(재고활용률+임박+저비용, 데이터 있으면 지금 가능) → **P1 LightGBM**(개인화). P1의 학습 피처 = *규칙 점수 3종 + **유저 행동 이력** + 레시피 인기도*.

**문제:** 실 PG 조사 결과(2026-07-16) **행동 데이터가 존재 자체를 안 함** — `user_event`·`활동`·`좋아요`·`app_user`·`pantry_item` 테이블 및 Kafka `events.user.activity` 토픽 **전부 없음**. 데이터가 없으면 ML은 학습 불가. 그래서 **무엇을·어떤 형태로** 쌓아야 하는지 이 문서로 요청한다.

> ⚠️ 행동 데이터는 **누적형**이라 지금 수집을 시작해도 유의미한 학습까진 시간이 걸린다. **P0 규칙 랭커로 서비스하면서 그 노출·클릭을 로깅해 P1용 데이터를 축적**하는 게 핵심 — 아래 §2.2(노출 로그)가 그 연결고리다.

## 2. 필요 데이터 (세부)

### 2.1 행동 이벤트 — 검증 결과 & 2층(A 즉시 유효 / B 기능 결정 선행)

⚠️ 이벤트는 그걸 발생시킬 **제품 기능**이 있어야 로깅된다. `ai-spec §3`의 6액션을 **실제 명세·스키마·API·프론트로 교차검증**(2026-07-16)한 결과 기능 성숙도가 갈린다 — 그래서 2층으로 나눈다. **A는 지금 계측 착수, B는 "이 기능을 만들 것인가"부터 결정** 필요.

**A. 기능 결정됨 → 계측(로깅)만 추가 — 지금 착수 가능**

| event_type | 의미 | 대상 | 신호 | 기능 근거(검증) |
|---|---|---|---|---|
| `VIEW` | 레시피 상세 조회 | recipe_id | 약한 관심(+) | ✅ **구현됨** — `GET /api/recipes/{id}` 실연동·`RecipeDetail.tsx` |
| `ADD_CART` | 장바구니 담기 | recipe_id | 강한 관심(++) | 🟢 **설계 확정** — `mealplan.cart_item`·MealPlan API·`Cart.tsx`(백킹 미마이그레이션) |
| `NOTIF_CLICK` | 알림 클릭 | recipe_id/item_id | 임박추천 반응 | 🟢 **설계됨** — `notify` 스키마·notification·타입4종(클릭추적만 신규) |

**B. 제품 기능 자체가 미결정 → "만들 것인가"부터 팀/기획 결정 필요**

| event_type | 의미 | 대상 | 신호 | 기능 근거(검증) |
|---|---|---|---|---|
| `DISCARD` | 재료 폐기 | item_id | 부정(−) | 🟡 개념만 — "안 버린 재료" 성과지표·`pantry status`(폐기 처리 UI 미결정) |
| `LIKE` | 좋아요 | recipe_id | 명시 선호 | 🔴 **미설계** — 인기도 *언급*뿐, `recipe_like` 테이블 없음(레시피북엔 공유만) |
| `COOKED` | 조리 완료 | recipe_id | 최강(+++) | 🔴 **백킹 0** — `ai-spec` 액션목록에만 존재 |

→ **B는 결정 전엔 스키마만 예약(수집 X).** `ai-spec §3` 자체가 클릭스트림 P0 편입을 "**팀 승인 대기**"로 둠 — B는 **기능 결정 + 수집 승인**의 이중 전제. 요청 우선순위 = **A + 노출로그(§2.2)부터**.

**공통 필드(모든 이벤트):** `user_id`·`event_type`·`occurred_at`(발생시각)·`session_id`(세션 그룹)·`context`(jsonb) + `recipe_id` 또는 `item_id`.

### 2.2 노출 로그(impression) — ⚠️ LTR의 핵심, 놓치면 학습 불가

**클릭만 로깅하면 안 된다.** "안 눌린 레시피(negative)"가 없어 편향된다. **랭커가 유저에게 보여준 레시피 목록 = 노출**을, 그 시점의 **순위·규칙점수와 함께** 남겨야 `(보여줌 → 눌림/안눌림)` 라벨을 만들 수 있다.

노출 1건 = **보여준 레시피 1개당 1행**(조인 편의):
- `user_id`, `session_id`, `shown_at`
- `recipe_id`, `rank`(노출 순위 1=최상단)
- **`rule_score` + 분해 3종(`score_stock`·`score_expiry`·`score_cost`)** — 그 시점 P0 규칙 점수(= P1 피처로 그대로 사용)
- `request_ctx`(jsonb: 예산잔여·의도 F11/F16·재고스냅샷 요약)

→ 라벨 = 이 노출 뒤 같은 세션에서 해당 recipe에 **VIEW/ADD_CART(A)** 가 발생했나(§2.1과 조인). `COOKED`(B)는 확정 시 최상단 강신호로 추가.

> 노출 로그는 기존 제품기능이 아니라 **랭커가 새로 emit**(AI 소유) — 제품기능 결정과 무관하게 **P0 규칙 랭커 구축과 함께** 생긴다. B 이벤트가 없어도 A만으로 학습 튜플이 성립.

### 2.3 레시피 인기도

`LIKE`·`COOKED`는 **B층(기능 미결정)** — 확정 전엔 인기도 집계 불가. 확정 시 이 이벤트 집계로 도출(별도 테이블 불필요). **그전까지 임시 인기도 = `ADD_CART`/`VIEW` 빈도 기반**(A층)으로 대체하다가 `LIKE` 확정 시 교체. 서빙 편의 위해 **집계 뷰**(`recipe_id → 인기도`) 제공 권장.

### 2.4 선행 의존 (현재 없는 base 테이블)

행동 이벤트가 참조할 FK 대상 + P0 규칙 입력이 아직 실 DB에 없음 — **먼저 생성 필요**:
- `app_user`(user_id) · `pantry_item`(재고·`expire_at` → 재고활용률·임박 계산) · `expense`(예산 → 저비용). 스키마 정의는 `prd/schema-app-oltp.md`에 있으나 **미마이그레이션**.

## 3. 저장 방식 요구 (ML이 쓰기 편한 형태)

### 3.1 파이프라인 (기존 Kafka→PG 패턴 재사용)

```
앱/백엔드(유저 액션·노출) ──produce──▶ Kafka events.user.activity
                                          └─consumer─▶ PG user_event / recipe_impression (append-only)
                                                              └─(AI) 주기 스냅샷 export ─▶ 학습 튜플(모델 X 아티팩트)
```
- 실시간 수집은 Kafka, 영속·조인은 PG. 학습은 **PG 1회 스냅샷**을 오프라인에서(NER `모델 X` 정책과 동일).

### 3.2 제안 DDL (backend 구현용 — schema-app-oltp 컨벤션)

```sql
CREATE TABLE user_event (
  id          bigserial PRIMARY KEY,
  user_id     bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  session_id  uuid,
  event_type  text NOT NULL CHECK (event_type IN
                ('VIEW','ADD_CART','COOKED','LIKE','DISCARD','NOTIF_CLICK')),
                -- 초기 실유입 = A층(VIEW·ADD_CART·NOTIF_CLICK)만. B층(COOKED·LIKE·DISCARD)은
                -- 해당 제품기능 확정 후 활성(§2.1). CHECK엔 미리 넣어 스키마 변경 없이 켜지게.
  recipe_id   bigint REFERENCES recipe(id),   -- 레시피 대상 이벤트
  item_id     bigint,                          -- 품목 대상(DISCARD 등) — item_master 논리참조
  occurred_at timestamptz NOT NULL,            -- 발생시각(UTC). 서버수신 아님, 클라 발생시각
  context     jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON user_event (user_id, occurred_at);
CREATE INDEX ON user_event (recipe_id, event_type);
CREATE INDEX ON user_event (event_type, occurred_at);

CREATE TABLE recipe_impression (
  id          bigserial PRIMARY KEY,
  user_id     bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  session_id  uuid,
  shown_at    timestamptz NOT NULL,
  recipe_id   bigint NOT NULL REFERENCES recipe(id),
  rank        int NOT NULL,
  rule_score  numeric,
  score_stock numeric, score_expiry numeric, score_cost numeric,  -- P1 피처
  request_ctx jsonb
);
CREATE INDEX ON recipe_impression (user_id, shown_at);
CREATE INDEX ON recipe_impression (recipe_id);
```

### 3.3 데이터 규칙 (꼭 지켜야 조인·학습 가능)

- **조인키 필수**: `user_id`·`recipe_id`·`item_id`를 이벤트에 반드시 실을 것 — 랭킹은 이걸로 pantry·recipe·item_master와 조인.
- **append-only·불변**: 이벤트는 UPDATE/DELETE 금지(이벤트 소싱). 정정은 새 이벤트로.
- **시각은 timestamptz(UTC)** + `occurred_at`은 **행동 발생시각**(서버 수신시각 아님) — 세션·순서 재구성용.
- `item_id`는 `DISCARD`·품목 이벤트에서 **NER이 붙인 표준품목코드**(냉장고·레시피와 동일 키).
- **세션 id**로 노출↔클릭을 같은 세션에서 묶을 수 있게.

### 3.4 ML 학습 편의 (이 형태면 바로 씀)

학습 1행(=랭킹 예시) = **노출 1건 ⋈ 그 세션의 후속 액션**:
```
(user_id, recipe_id,
 features = [score_stock, score_expiry, score_cost, 유저이력집계, recipe 인기도],
 label    = 그 노출 뒤 ADD_CART>VIEW>무반응 순 관련도 [A층만으로 성립]. COOKED(B) 확정 시 최상단 추가)
```
→ `recipe_impression`(피처·순위) + `user_event`(라벨)만 있으면 **LightGBM LTR 튜플이 SQL 조인 한 번으로** 나옴. 그래서 §2.2 노출 로그가 결정적.

## 4. 거버넌스 (수집 전 필수)

- **수집 동의**: `app_user`에 `activity_consent boolean`·`consented_at` 두고 **동의 유저만** 로깅. 미동의 유저 이벤트는 produce 금지.
- **팀 승인**: 클릭스트림 P0 편입은 `ai-spec §3`대로 **팀 승인 대기** — 승인 후 수집 시작.
- **보존정책**: 원시 이벤트 보존기간(예: 180일) + 이후 집계본만 — 협의 필요.
- **PII 최소화**: 이벤트에 개인식별정보(주소·연락처) 미포함, user_id(내부키)만.

## 5. 볼륨 추정 (참고 — 단일 PG 충분 재확인)

DAU 500 가정: 이벤트 ~1~1.5만/일, 노출 ~2~3만/일 → 월 ~100만 행. `design.md §용량`의 "단일 PG 충분" 범위 내. 파티셔닝은 규모 커지면 `occurred_at` 월 파티션 검토.

## 6. 담당 분리

| 항목 | 담당 |
|---|---|
| `app_user`·`pantry_item`·`expense`·`user_event`·`recipe_impression` 테이블 생성·마이그레이션 | **백엔드/데이터** |
| Kafka `events.user.activity` 토픽 + 컨슈머(→PG) | **데이터** |
| 앱에서 6이벤트 produce + 동의 게이팅 | **백엔드/프론트** |
| **노출 로그 produce**(랭커가 점수·순위와 함께) | **AI(건우) 랭커** ↔ 저장은 데이터 |
| 학습 스냅샷 export·LightGBM 학습·서빙 | **AI(건우)** |

## 7. 미결/질문 (회신 요청)

1. **⚠️ B층 제품기능 신설 결정**(가장 중요): `COOKED`(조리완료)·`LIKE`(좋아요)·`DISCARD`(폐기 처리) — **이 기능들을 만들 것인가**를 기획/팀이 먼저 결정. 결정 전엔 스키마만 예약, 수집 X. (검증 결과 COOKED·LIKE는 백킹 0/미설계.)
2. 위 DDL·**A층 이벤트**(VIEW·ADD_CART·NOTIF_CLICK)·노출로그·필드 **동의 여부**(추가/수정 필요?).
3. `events.user.activity` **토픽 스키마**(JSON/Avro?) 합의.
4. `app_user`·`pantry_item` **마이그레이션 일정** — P0 규칙 랭커도 이게 있어야 실데이터 동작.
5. 수집 **동의·팀 승인** 진행 상태(클릭스트림 P0 편입).
6. 노출 로그 produce 지점(랭커 서비스) ↔ 싱크(토픽/테이블) 인터페이스 확정.
