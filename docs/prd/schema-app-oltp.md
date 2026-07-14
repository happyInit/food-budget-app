# 앱 OLTP 스키마 제안 (유저 생성 데이터) — 초안

> **상태: 제안 초안 (2026-07-14).** 확정 아님. [§6 결정 필요](#6-결정-필요-담당자-확정)의 항목은 데이터/백엔드 담당 검토 후 확정.
>
> **근거:** [`docs/design/api-spec.md`](../design/api-spec.md) 엔드포인트 + `frontend/` 화면이 실제 요구하는 필드에서 파생.
>
> **관계:** 데이터 티어 스키마 [`docs/prd/schema-public-data.sql`](./schema-public-data.sql)(크롤·공공데이터, 읽기 소스)와 조인. 이 문서는 **유저가 쓰는(write) 저장소**만 다룸.

---

## 0. 배경 · 범위

| 구분 | 스키마 | 성격 | 위치 |
|---|---|---|---|
| **데이터 티어** (기존) | `item_master`·`recipe`·`price_*`·`retail_*`·`food_nutrition`·`shelf_life_ref` | 크롤·공공데이터로 채우는 **읽기 소스** | `schema-public-data.sql` |
| **앱 OLTP** (이 문서) | 아래 §3 | 유저가 생성하는 **쓰기 데이터** | 미정의 → 제안 |

현재 `api-spec.md`엔 User·Pantry·Expense·MealPlan·Notification 엔드포인트가 있지만 **백킹 테이블이 없다.** 이 문서가 그 공백을 메우는 제안이다.

**대상 도메인:** Auth/User(계정·예산) · Pantry(냉장고·OCR) · Expense(식비) · MealPlan(장바구니) · Recipe(레시피북·YouTube추출) · Price(최저가 관심) · Notification(알림).

---

## 1. 선결 결정 — OLTP DB 분리 여부 (결정 필요 #1)

데이터 티어는 **fb-data(.8) `foodbudget`** DB에 있고, 커밋 `fc25331`에서 **앱 OLTP DB 분리**가 언급됨.

- **다른 DB/인스턴스면** → 데이터 티어(`item_master`·`recipe`·`retail_product`)로의 **cross-DB FK가 불가.**
  이 초안은 그 참조들을 **논리적 참조(plain `bigint`, FK 미설정)** 로 두고 `-- ▶` 주석 처리했다.
- **같은 DB(스키마만 분리)면** → 주석 처리된 참조를 **진짜 FK로 승격**하면 된다.

> 아래 DDL은 **분리(논리참조)** 를 기본값으로 작성. 같은 DB로 확정되면 `-- ▶item_master 논리참조` 줄을 `item_id bigint REFERENCES item_master(item_id)` 로 바꾸면 됨.

---

## 2. 컨벤션 (데이터 티어와 동일)

- PK: `bigserial PRIMARY KEY`
- 시각: `timestamptz NOT NULL DEFAULT now()`
- 이름/식별자: `snake_case`
- enum: `text ... CHECK (col IN (...))` — 별도 타입 안 씀 (기존 `storage`·`ner_status`와 동일 방식)
- 금액: `numeric` (KRW; `retail_price.price`와 일관)
- 프론트 파생값(`emoji`·`iconBg`·`tone`·`dday`·`percent`·포맷된 `₩` 문자열)은 **저장 안 함** — 서버는 원시값(`numeric`·`date`·`type`)만, 표시는 프론트가 변환.

---

## 3. 테이블 제안 (11개 + 설정 1)

### 3.1 계정 · 예산

```sql
-- app_user — Auth #2~6, User #7~8
CREATE TABLE app_user (
  id            bigserial PRIMARY KEY,
  email         text UNIQUE,               -- 카카오 전용이면 null 허용
  password_hash text,                        -- 자체 로그인만; 카카오면 null
  nickname      text NOT NULL,
  provider      text NOT NULL DEFAULT 'local' CHECK (provider IN ('local','kakao')),
  provider_uid  text,                        -- 카카오 회원번호
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (provider, provider_uid)
);

-- user_budget — User #9~10 (월 예산). 프론트: 예산설정(SCR-004)·홈 히어로(005)·식비 요약(014)
CREATE TABLE user_budget (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  month      date NOT NULL,                  -- 매월 1일로 정규화 (예: 2026-07-01)
  amount     numeric NOT NULL,               -- 월 예산액(KRW)
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, month)
);
```

### 3.2 냉장고 (Pantry)

```sql
-- pantry_item — Pantry #11~15. 프론트: 냉장고 재고(006)·임박·성과(016) '안 버린 재료'
CREATE TABLE pantry_item (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  -- item_id  bigint,   -- ▶item_master 논리참조 (표준품목·영양·emoji 매핑)
  name       text NOT NULL,                  -- 표시명(원문/수기)
  quantity   text,                           -- '1단','500g','8구' (원문 유지)
  storage    text NOT NULL CHECK (storage IN ('ROOM','FRIDGE','FREEZER')),  -- shelf_life_ref와 동일 enum
  expire_at  date,                           -- shelf_life_ref 추정 or 유저입력 (dday는 프론트 계산)
  source     text NOT NULL DEFAULT 'MANUAL' CHECK (source IN ('MANUAL','OCR')),
  status     text NOT NULL DEFAULT 'ACTIVE'  CHECK (status IN ('ACTIVE','CONSUMED','DISCARDED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  closed_at  timestamptz                     -- 소진/폐기 시각 → 성과지표 '안 버린 재료 %' 산출
);
CREATE INDEX ON pantry_item (user_id, status);
CREATE INDEX ON pantry_item (user_id, expire_at);

-- ocr_receipt / ocr_receipt_item — Pantry #16~17 (영수증 OCR, 비동기 job). 프론트: OCR등록(007)·결과(008)
CREATE TABLE ocr_receipt (
  id           bigserial PRIMARY KEY,
  user_id      bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  status       text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','DONE','FAILED')),
  store        text,                          -- 인식 매장명 (예: GS25)
  purchased_at timestamptz,
  total_amount numeric,
  created_at   timestamptz NOT NULL DEFAULT now()
  -- 원본 이미지 URL은 미저장(설계: 분석에만 사용). 보관 정책 바뀌면 컬럼 추가.
);
CREATE TABLE ocr_receipt_item (               -- 확정 전 파싱 결과(유저가 수정→확정). 결정 필요 #3
  id          bigserial PRIMARY KEY,
  receipt_id  bigint NOT NULL REFERENCES ocr_receipt(id) ON DELETE CASCADE,
  raw_text    text,                           -- '삼겹500'
  name        text,                           -- 매칭 표시명 '돼지고기 삼겹살'
  -- item_id  bigint,   -- ▶item_master 논리참조 (NER 결과)
  quantity    text,
  price       numeric,
  is_food     boolean NOT NULL DEFAULT true,  -- '봉투' 등 비재료 제외
  confirmed   boolean NOT NULL DEFAULT false
);
```

### 3.3 식비 (Expense)

```sql
-- expense — Expense #38~40. 프론트: 캘린더(014)·지출추가(015)·성과(016)
CREATE TABLE expense (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  amount     numeric NOT NULL,
  category   text NOT NULL CHECK (category IN ('GROCERY','DINING','DELIVERY','ETC')),  -- 장보기/외식/배달/기타
  spent_on   date NOT NULL,                   -- 캘린더 집계 키
  memo       text,
  source     text NOT NULL DEFAULT 'MANUAL' CHECK (source IN ('MANUAL','OCR','CART')),
  receipt_id bigint REFERENCES ocr_receipt(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON expense (user_id, spent_on);
```

### 3.4 장보기 (Cart)

```sql
-- cart_item — MealPlan #33~36 (유저당 단일 active 장바구니). 프론트: 장바구니(013)
-- 가격은 저장 안 하고 retail_price에서 실시간 조회(결정 필요 #6). name만 스냅샷.
CREATE TABLE cart_item (
  id                bigserial PRIMARY KEY,
  user_id           bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  -- retail_product_id bigint,  -- ▶retail_product 논리참조 (현재가·매장 source)
  -- recipe_id         bigint,  -- ▶recipe 논리참조 (어떤 레시피에서 담겼나)
  -- item_id           bigint,  -- ▶item_master 논리참조
  name              text NOT NULL,            -- 스냅샷 표시명
  quantity          text,
  added_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON cart_item (user_id);
-- 장보기 완료(#36 checkout) = cart_item 정리 + expense(source='CART') 생성.
-- 주문 이력 테이블(shopping_order)은 결정 필요 #4에서.
```

### 3.5 레시피북 · 관심 · 알림

```sql
-- recipe_book — Recipe #20~23. 프론트: 내 레시피북(019)
CREATE TABLE recipe_book (
  id          bigserial PRIMARY KEY,
  user_id     bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  -- recipe_id bigint,  -- ▶recipe 논리참조 (SAVED일 때). EXTRACTED/CUSTOM 저장위치는 결정 필요 #2
  source_type text NOT NULL CHECK (source_type IN ('SAVED','EXTRACTED','CUSTOM')),
  title       text NOT NULL,
  is_public   boolean NOT NULL DEFAULT false,
  share_token text UNIQUE,                    -- 공유 URL(#23)
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- recipe_extract_job — Recipe #24~25 (YouTube 추출, 비동기). 프론트: YouTube추출(020)
CREATE TABLE recipe_extract_job (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  url        text NOT NULL,
  status     text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','DONE','FAILED')),
  result     jsonb,                           -- 추출 재료·단계(저장 전 미리보기)
  created_at timestamptz NOT NULL DEFAULT now()
);

-- price_watch — Price #29~30 (최저가 관심). 멘토 피드백: 최저가 알림 fan-out 소스
CREATE TABLE price_watch (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  -- item_id  bigint,   -- ▶item_master 논리참조 (품목 단위 관심)
  created_at timestamptz NOT NULL DEFAULT now()
  -- UNIQUE (user_id, item_id)  -- item_id FK 승격 시 활성화
);

-- notification — Notification #41~42. 프론트: 알림함(017)·드롭다운/바텀시트
-- emoji/iconBg/to(딥링크)는 프론트가 type으로 파생 — 미저장.
CREATE TABLE notification (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  type       text NOT NULL CHECK (type IN ('LOW_PRICE','EXPIRING','HOTDEAL','BUDGET')),
  title      text NOT NULL,
  body       text,
  payload    jsonb,                           -- {item_id, recipe_id, deal_id…} 딥링크 데이터
  is_read    boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON notification (user_id, is_read, created_at DESC);

-- notification_setting — Notification #43~44 (유저당 1행). 결정 필요 #5
CREATE TABLE notification_setting (
  user_id    bigint PRIMARY KEY REFERENCES app_user(id) ON DELETE CASCADE,
  low_price  boolean NOT NULL DEFAULT true,
  expiry     boolean NOT NULL DEFAULT true,
  hotdeal    boolean NOT NULL DEFAULT true,
  budget     boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);
```

---

## 4. 데이터 티어 조인 지도 (논리참조)

| OLTP 컬럼 | → 데이터 티어 | 용도 |
|---|---|---|
| `pantry_item.item_id` · `ocr_receipt_item.item_id` · `price_watch.item_id` | `item_master` | 표준품목·영양·emoji 매핑 |
| `pantry_item` (storage + item) | `shelf_life_ref` | 유통기한 임박일 추정 |
| `cart_item.retail_product_id` | `retail_product` / `retail_price` | 현재가·매장·핫딜 |
| `cart_item.recipe_id` · `recipe_book.recipe_id` | `recipe` | 레시피 연결 |

---

## 5. api-spec 커버리지

| api-spec # | 엔드포인트 | 백킹 테이블 |
|---|---|---|
| 2~6 | `/api/auth/*` | `app_user` |
| 7~8 | `/api/users/me` | `app_user` |
| 9~10 | `/api/users/budget` | `user_budget` |
| 11~15 | `/api/pantry/items`·`/expiring` | `pantry_item` |
| 16~17 | `/api/pantry/ocr` | `ocr_receipt`·`ocr_receipt_item` |
| 20~23 | `/api/recipes/book` | `recipe_book` |
| 24~25 | `/api/recipes/extract` | `recipe_extract_job` |
| 29~30 | `/api/prices/watch` | `price_watch` |
| 33~36 | `/api/mealplan/cart` | `cart_item` (+ `expense` on checkout) |
| 38~40 | `/api/expenses/*` | `expense` |
| 41~42 | `/api/notifications` | `notification` |
| 43~44 | `/api/notifications/settings` | `notification_setting` |

**테이블 불필요(stateless/데이터 티어):** #18~19 레시피 검색·상세(`recipe*`), #26~28·31 시세·핫딜(`price_*`·`retail_*`), #32 추천(계산), #37 어시스턴트(RAG), #45~47 ML 내부.

---

## 6. 결정 필요 (담당자 확정)

1. **OLTP DB 분리 여부** → 진짜 FK vs 논리참조(초안 기본값). §1.
2. **유저 레시피 저장 위치** — YouTube추출/직접작성분을 `recipe`에 `source='USER'` 확장 vs 별도 `user_recipe` 테이블. 초안은 `recipe_book.source_type`만 두고 본문은 유보.
3. **OCR 파싱 결과 형태** — 정규화 `ocr_receipt_item`(초안) vs `ocr_receipt.result jsonb` 단일 컬럼.
4. **장바구니 범위** — 유저당 단일 active cart(초안, 간단) vs cart 헤더 + 주문 이력(`shopping_order`) 유지.
5. **알림 설정 위치** — 별도 `notification_setting`(초안) vs `app_user` 컬럼 인라인.
6. **가격 스냅샷** — `cart_item` 담을 때 가격 고정 vs 항상 실시간 조회(초안).
7. **`meal_plan` 저장 필요 여부** — `POST /mealplan/recommend`가 stateless면 불필요(초안엔 없음). "며칠치 플랜" 영속화가 필요하면 추가.

---

## 7. 다음 단계

1. 위 §6 확정 → 이 문서 반영
2. 확정본을 `schema-app-oltp.sql`(적용용 DDL)로 구현 + `apply_schema.py` 계열로 멱등 적용
3. `api-spec.md`의 해당 엔드포인트 **응답 스키마 상세화**(필드·타입)를 이 테이블 기준으로 채움
4. 프론트 `mock.ts` → 실제 응답 shape로 정렬 후 TanStack Query 훅 연동
