# 유저 행동 데이터 요청서 — 개인화 레시피 랭킹(P1, LightGBM)

> **작성:** 건우 (AI 담당) · 2026-07-16
> **수신:** 데이터 담당 · 백엔드 개발자
> **목적:** P1 개인화 레시피 랭킹(LightGBM) **학습·서빙에 필요한 유저 행동 데이터**의 수집·저장 요청
> **상태:** 요청(설계 협의 필요) · 근거 `ai-spec.md §3` · **수집 동의·P0 편입 팀 승인 전제**

---

## 1. 배경 (왜 요청하나)

개인화 레시피 랭킹은 2단계다(`ai-spec §3`): **P0 규칙**(재고활용률+임박+저비용, 데이터 있으면 지금 가능) → **P1 LightGBM**(개인화). P1의 학습 피처 = *규칙 점수 3종 + **유저 행동 이력** + 레시피 인기도*.

**문제:** 실 PG 조사 결과(2026-07-16) **행동 데이터가 존재 자체를 안 함** — `user_event`·`활동`·`좋아요`·`app_user`·`pantry_item` 테이블 및 Kafka `events.user.activity` 토픽 **전부 없음**. 데이터가 없으면 ML은 학습 불가. 그래서 **무엇을·어떤 형태로** 쌓아야 하는지 이 문서로 요청한다.

> ⚠️ 행동 데이터는 **누적형**이라 지금 수집을 시작해도 유의미한 학습까진 시간이 걸린다. **P0 규칙 랭커로 서비스하면서 그 노출·클릭을 로깅해 P1용 데이터를 축적**하는 게 핵심 — 아래 §2.2(노출 로그)가 그 연결고리다.

## 2. 필요 데이터 (세부)

### 2.1 행동 이벤트 6종 (필수)

`ai-spec §3`의 6액션. **모든 이벤트 공통 필드** + 타입별 대상:

| event_type | 의미 | 대상 키 | 랭킹에서의 신호 |
|---|---|---|---|
| `VIEW` | 레시피 상세 조회 | recipe_id | 약한 관심(+) |
| `ADD_CART` | 장바구니 담기 | recipe_id | 강한 관심(++) |
| `COOKED` | 조리 완료 | recipe_id | 최강 긍정(+++) |
| `LIKE` | 좋아요 | recipe_id | 명시적 선호 + **인기도 집계원** |
| `DISCARD` | 재료 폐기 | **item_id** | 부정 신호(해당 재료 회피) |
| `NOTIF_CLICK` | 임박/딜 알림 클릭 | recipe_id 또는 item_id | 임박추천 반응 |

**공통 필드(모든 이벤트):** `user_id`(스코프), `event_type`, `occurred_at`(발생시각), `session_id`(세션 그룹), `context`(jsonb 부가맥락). 대상은 이벤트에 따라 `recipe_id` 또는 `item_id`.

### 2.2 노출 로그(impression) — ⚠️ LTR의 핵심, 놓치면 학습 불가

**클릭만 로깅하면 안 된다.** "안 눌린 레시피(negative)"가 없어 편향된다. **랭커가 유저에게 보여준 레시피 목록 = 노출**을, 그 시점의 **순위·규칙점수와 함께** 남겨야 `(보여줌 → 눌림/안눌림)` 라벨을 만들 수 있다.

노출 1건 = **보여준 레시피 1개당 1행**(조인 편의):
- `user_id`, `session_id`, `shown_at`
- `recipe_id`, `rank`(노출 순위 1=최상단)
- **`rule_score` + 분해 3종(`score_stock`·`score_expiry`·`score_cost`)** — 그 시점 P0 규칙 점수(= P1 피처로 그대로 사용)
- `request_ctx`(jsonb: 예산잔여·의도 F11/F16·재고스냅샷 요약)

→ 라벨 = 이 노출 뒤 같은 세션에서 해당 recipe에 VIEW/ADD_CART/COOKED가 발생했나(§2.1과 조인).

### 2.3 레시피 인기도

`LIKE`(+`COOKED`) 이벤트에서 **집계**로 도출 가능 → 별도 테이블 불필요. 다만 서빙 편의를 위해 **집계 뷰/머티리얼라이즈드뷰**(`recipe_id → like_count, cook_count`) 하나 제공 권장(랭킹 서빙 시 실시간 계산 회피).

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
 label    = 그 노출 뒤 COOKED>ADD_CART>VIEW>무반응 순 관련도)
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

1. 위 DDL·이벤트 6종·필드 **동의 여부**(추가/수정 필요 필드?).
2. `events.user.activity` **토픽 스키마**(JSON/Avro?) 합의.
3. `app_user`·`pantry_item` **마이그레이션 일정** — P0 규칙 랭커도 이게 있어야 실데이터 동작.
4. 수집 **동의·팀 승인** 진행 상태.
5. 노출 로그 produce 지점(랭커 서비스) ↔ 싱크(토픽/테이블) 인터페이스 확정.
