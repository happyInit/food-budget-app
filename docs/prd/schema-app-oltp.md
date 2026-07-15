# 앱 OLTP 스키마 제안 (유저 생성 데이터) — 초안

> ⚠️ **참고용 초안 (superseded).** 스키마 SSOT는 [`schema-production.md`](./schema-production.md). 이 문서는 설계 논의 이력이며 더 이상 정본이 아니다 — 스키마 작업은 SSOT에 기록.

> **상태: 제안 초안 (2026-07-14 작성, 2026-07-15 갱신).**
> - **확정(2026-07-15):** §1 DB 분리 방식 = **스키마-퍼-서비스(단일 PG) + 데이터 티어 공유 읽기** · `cart_item.qty` 계산 컬럼 분리.
> - **미확정:** [§6](#6-결정-필요-담당자-확정) #2~7 — 데이터/백엔드 담당 검토 후 확정.
>
> **근거:** [`docs/design/api-spec.md`](../design/api-spec.md) 엔드포인트 + `frontend/` 화면이 실제 요구하는 필드에서 파생.
>
> **관계:** 데이터 티어 스키마 [`docs/prd/schema-public-data.sql`](./schema-public-data.sql)(크롤·공공데이터, 읽기 소스)와 조인. 이 문서는 **유저가 쓰는(write) 저장소**만 다룸.

---

## 0. 배경 · 범위

| 구분 | 스키마 | 성격 | 위치 |
|---|---|---|---|
| **데이터 티어** (기존) | `item_master`·`recipe`·`price_*`·`retail_*`·`food_nutrition`·`shelf_life_ref` | 크롤·공공데이터로 채우는 **읽기 소스** | `schema-public-data.sql` (현재 `foodbudget.public`) |
| **앱 OLTP** (이 문서) | 아래 §3 | 유저가 생성하는 **쓰기 데이터** | 서비스별 스키마 (신규) |

현재 `api-spec.md`엔 User·Pantry·Expense·MealPlan·Notification 엔드포인트가 있지만 **백킹 테이블이 없다.** 이 문서가 그 공백을 메우는 제안이다.

**대상 도메인:** Auth/User(계정·예산) · Pantry(냉장고·OCR) · Expense(식비) · MealPlan(장바구니) · Recipe(레시피북·YouTube추출) · Price(최저가 관심) · Notification(알림).

---

## 1. DB 분리 방식 — **확정 (2026-07-15)**

**스키마-퍼-서비스 (단일 PostgreSQL 인스턴스·단일 DB) + 데이터 티어 공유 읽기.**

> **위치 = 의도된 하이브리드.** 경계는 MSA(서비스별 스키마 소유 · role 격리 · 크로스-서비스는 API 통신 · 크로스-서비스 FK 없음 → `user_id`는 JWT로 신뢰), 물리는 모놀리스(**단일 DB** · 공유 읽기 `data`에만 진짜 FK). 완전 MSA(DB-per-service·API-only)까진 DAU 500에 과함. *모놀리스성의 뿌리는 공유 카탈로그가 아니라 **단일 물리 DB** — 카탈로그 공유는 그 위에 얹은 추가 결합.*

- 서비스마다 **자기 스키마**를 소유하고, 서비스 role은 **자기 스키마 + 읽기전용 `data` 스키마(SELECT)만** GRANT.
  → 어떤 서비스도 **다른 서비스의 쓰기 스키마에 접근 불가**(PostgreSQL 기본이 거부 + GRANT로만 열림). "남의 서비스 DB 참조 금지"를 role로 강제.
- 공용 카탈로그(recipe·price·nutrition·shelf_life)는 어느 서비스의 사유 데이터가 아니라 **수집 파이프라인이 소유한 읽기전용 카탈로그** → 전 서비스가 함께 SELECT. 그래서 장바구니 가격조인이 **단일 쿼리로 유지**된다.
- DAU 500 규모(§design.md §8.3)엔 물리 분리(DB/인스턴스 분할) 이득이 없음. 특정 서비스 부하가 실제로 커지면 그 스키마만 **별도 DB로 승격** 가능 — 승격 비용은 §1.4.

### 1.1 스키마 배치

| 스키마 | 서비스 | 테이블 |
|---|---|---|
| `account` | Auth + User | `app_user`, `user_budget` |
| `pantry` | Pantry | `pantry_item`, `ocr_receipt`, `ocr_receipt_item` |
| `mealplan` | MealPlan (+ Expense) | `cart_item`, `expense` |
| `cookbook` | Recipe | `recipe_book`, `recipe_extract_job` |
| `price` | Price | `price_watch` |
| `notify` | Notification | `notification`, `notification_setting` |
| `data` | (수집 파이프라인) | 데이터 티어 전체 — **읽기전용 공용** |

> Auth·User는 `app_user`를 공유(한 테이블은 스키마를 못 쪼갬)하므로 **한 스키마 `account`**. 스키마명은 제안 — 팀 합의로 변경 가능.
> `data` 스키마: 데이터 티어는 현재 `foodbudget.public`에 있음. `data` 스키마로 옮기거나 `public`을 공용 읽기로 GRANT — **소소한 마이그레이션(별도 처리).** 아래 DDL은 `data.*`로 표기.

### 1.2 참조(FK) 정책 — 이 결정의 직접 귀결

| 참조 종류 | 정책 | 예 |
|---|---|---|
| **같은 스키마 내** | **진짜 FK** (+ CASCADE) | `ocr_receipt`→`ocr_receipt_item`, `app_user`→`user_budget` |
| **크로스-서비스** (→ 다른 서비스 스키마) | **FK 없음 · 논리 `bigint` 값** | 모든 `*.user_id` (JWT 신뢰), `expense.receipt_id` |
| **→ `data` 스키마** (공용 읽기) | **진짜 FK · `ON DELETE SET NULL`** | `cart_item.retail_product_id`→`data.retail_product` |

- **크로스-서비스 FK 제거의 대가:** 유저 삭제 시 DB CASCADE가 안 됨 → 각 서비스가 `user.deleted` 이벤트를 받아 자기 데이터를 정리(또는 배치 클린업). MSA 표준 패턴.
- **`data` 참조에 `SET NULL`:** 카탈로그 재적재·프루닝으로 참조 대상이 사라져도 앱 쓰기 행이 막히지 않게(스냅샷 `name`은 유지). `item_id`는 원래 nullable(매칭 ~89%).

### 1.3 role / GRANT 스케치 (격리 강제)

```sql
CREATE SCHEMA account; CREATE SCHEMA pantry; CREATE SCHEMA mealplan;
CREATE SCHEMA cookbook; CREATE SCHEMA price; CREATE SCHEMA notify;
-- data 스키마 = 기존 데이터 티어(읽기전용 공용)

-- 서비스마다 동일 패턴 (예: account)
CREATE ROLE svc_account LOGIN PASSWORD :'pw';
GRANT USAGE, CREATE ON SCHEMA account TO svc_account;         -- 자기 스키마 소유
GRANT USAGE  ON SCHEMA data TO svc_account;                   -- 공용 카탈로그 읽기
GRANT SELECT ON ALL TABLES IN SCHEMA data TO svc_account;
ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT ON TABLES TO svc_account;
-- svc_account 는 pantry/mealplan/cookbook/price/notify 에 아무 GRANT 없음
--   → PostgreSQL 기본 거부라 크로스서비스 접근 자동 차단(명시 REVOKE 불필요).
```

### 1.4 승격(스키마→DB) 이전 용이성

이 배치는 나중에 **핫한 서비스 하나씩** DB-per-service로 뗄 수 있게 설계됨.

- **쓰기 경계 이전은 용이** — 크로스-서비스 FK가 이미 없고(§1.2), role로 크로스-스키마 쓰기를 애초에 안 하므로, `pg_dump -n <schema>` → 새 DB restore → 커넥션 리포인트면 됨. 트랜잭션이 스키마를 안 넘어서 안 깨짐.
- **비용은 `data` 티어 조인뿐** — 옮긴 서비스는 `data`와 다른 DB가 되므로 `data.*` FK가 깨짐 → **논리 `bigint`로 강등** + 그 조인을 **앱 조합 / `postgres_fdw` / `data` 읽기복제**로 대체.
- **서비스별 난이도** (data 조인 의존도 순): `notify`·`cookbook`·`account` 🟢 거의 `pg_dump`만 · `pantry` 🟡 조인 대체 · `mealplan` 🔴 가격조인 재작업 큼.

→ 즉 **쓰기 모델은 재작성 없이 이전**되고, 재작업은 `data` 조인이 무거운 서비스에 국한. 이게 스키마-퍼-서비스를 택한 핵심 이득(값싼 승격 옵션).

---

## 2. 컨벤션 (데이터 티어와 동일 + 스키마-퍼-서비스)

- 테이블은 **소유 스키마에 생성**: `CREATE TABLE <schema>.<table>`.
- PK: `bigserial PRIMARY KEY`
- 시각: `timestamptz NOT NULL DEFAULT now()`
- 이름/식별자: `snake_case`
- enum: `text ... CHECK (col IN (...))` — 별도 타입 안 씀 (기존 `storage`·`ner_status`와 동일 방식)
- 금액: `numeric` (KRW; `retail_price.price`와 일관)
- **크로스-서비스 참조 = 논리 `bigint` 값**(FK 미설정) — `user_id`는 JWT가 준 값을 신뢰. `data` 티어 참조만 진짜 FK.
- 프론트 파생값(`emoji`·`iconBg`·`tone`·`dday`·`percent`·포맷된 `₩` 문자열)은 **저장 안 함** — 서버는 원시값(`numeric`·`date`·`type`)만, 표시는 프론트가 변환.

---

## 3. 테이블 제안 (11개 + 설정 1)

### 3.1 계정 · 예산 — `account`

```sql
-- app_user — Auth #2~6, User #7~8
CREATE TABLE account.app_user (
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
CREATE TABLE account.user_budget (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL REFERENCES account.app_user(id) ON DELETE CASCADE,  -- 같은 스키마 → FK 유지
  month      date NOT NULL,                  -- 매월 1일로 정규화 (예: 2026-07-01)
  amount     numeric NOT NULL,               -- 월 예산액(KRW)
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, month)
);
```

### 3.2 냉장고 (Pantry) — `pantry`

```sql
-- pantry_item — Pantry #11~15. 프론트: 냉장고 재고(006)·임박·성과(016) '안 버린 재료'
CREATE TABLE pantry.pantry_item (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,                -- ▶account.app_user 논리참조(크로스서비스·FK X·JWT 신뢰)
  item_id    bigint REFERENCES data.item_master(item_id) ON DELETE SET NULL,  -- data 공용읽기 → FK
  name       text NOT NULL,                  -- 표시명(원문/수기)
  quantity   text,                           -- '1단','500g','8구' (원문 유지)
  storage    text NOT NULL CHECK (storage IN ('ROOM','FRIDGE','FREEZER')),  -- shelf_life_ref와 동일 enum
  expire_at  date,                           -- shelf_life_ref 추정 or 유저입력 (dday는 프론트 계산)
  source     text NOT NULL DEFAULT 'MANUAL' CHECK (source IN ('MANUAL','OCR')),
  status     text NOT NULL DEFAULT 'ACTIVE'  CHECK (status IN ('ACTIVE','CONSUMED','DISCARDED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  closed_at  timestamptz                     -- 소진/폐기 시각 → 성과지표 '안 버린 재료 %' 산출
);
CREATE INDEX ON pantry.pantry_item (user_id, status);
CREATE INDEX ON pantry.pantry_item (user_id, expire_at);

-- ocr_receipt / ocr_receipt_item — Pantry #16~17 (영수증 OCR, 비동기 job). 프론트: OCR등록(007)·결과(008)
CREATE TABLE pantry.ocr_receipt (
  id           bigserial PRIMARY KEY,
  user_id      bigint NOT NULL,               -- ▶account.app_user 논리참조(크로스서비스·FK X)
  status       text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','DONE','FAILED')),
  store        text,                          -- 인식 매장명 (예: GS25)
  purchased_at timestamptz,
  total_amount numeric,
  created_at   timestamptz NOT NULL DEFAULT now()
  -- 원본 이미지 URL은 미저장(설계: 분석에만 사용). 보관 정책 바뀌면 컬럼 추가.
);
CREATE TABLE pantry.ocr_receipt_item (        -- 확정 전 파싱 결과(유저가 수정→확정). 결정 필요 #3
  id          bigserial PRIMARY KEY,
  receipt_id  bigint NOT NULL REFERENCES ocr_receipt(id) ON DELETE CASCADE,  -- 같은 스키마 → FK
  raw_text    text,                           -- '삼겹500'
  name        text,                           -- 매칭 표시명 '돼지고기 삼겹살'
  item_id     bigint REFERENCES data.item_master(item_id) ON DELETE SET NULL,  -- data (NER 결과)
  quantity    text,
  price       numeric,
  is_food     boolean NOT NULL DEFAULT true,  -- '봉투' 등 비재료 제외
  confirmed   boolean NOT NULL DEFAULT false
);
```

### 3.3 식비 (Expense) — `mealplan`

```sql
-- expense — Expense #38~40. 프론트: 캘린더(014)·지출추가(015)·성과(016)
CREATE TABLE mealplan.expense (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,                 -- ▶account.app_user 논리참조(크로스서비스·FK X)
  amount     numeric NOT NULL,
  category   text NOT NULL CHECK (category IN ('GROCERY','DINING','DELIVERY','ETC')),  -- 장보기/외식/배달/기타
  spent_on   date NOT NULL,                   -- 캘린더 집계 키
  memo       text,
  source     text NOT NULL DEFAULT 'MANUAL' CHECK (source IN ('MANUAL','OCR','CART')),
  receipt_id bigint,                          -- ▶pantry.ocr_receipt 논리참조(크로스서비스·FK X)
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON mealplan.expense (user_id, spent_on);
```

### 3.4 장보기 (Cart) — `mealplan`

```sql
-- cart_item — MealPlan #33~36 (유저당 단일 active 장바구니). 프론트: 장바구니(013)
-- 가격은 저장 안 하고 retail_price에서 실시간 조회(결정 필요 #6). name만 스냅샷.
CREATE TABLE mealplan.cart_item (
  id                bigserial PRIMARY KEY,
  user_id           bigint NOT NULL,          -- ▶account.app_user 논리참조(크로스서비스·FK X)
  retail_product_id bigint REFERENCES data.retail_product(id)   ON DELETE SET NULL,  -- data (현재가·매장)
  recipe_id         bigint REFERENCES data.recipe(id)           ON DELETE SET NULL,  -- data (어떤 레시피에서)
  item_id           bigint REFERENCES data.item_master(item_id) ON DELETE SET NULL,  -- data
  name              text NOT NULL,            -- 스냅샷 표시명
  qty               int NOT NULL DEFAULT 1,   -- 담은 팩 개수(계산용) — total = Σ(현재가 × qty)
  quantity          text,                     -- 표시용 원문('2개','1단') — 산술 대상 아님
  added_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON mealplan.cart_item (user_id);
-- 장보기 완료(#36 checkout) = cart_item 정리 + expense(source='CART') 생성.
-- 주문 이력 테이블(shopping_order)은 결정 필요 #4에서.
-- qty(int, 계산) vs quantity(text, 표시) 분리 — 장바구니 합계 산술 위해 (2026-07-15 보정,
--   근거: 장바구니 가격 조인 total=Σ(단가×qty)에 곱할 수 있는 숫자가 필요).
```

### 3.5 레시피북 (`cookbook`) · 관심 (`price`) · 알림 (`notify`)

```sql
-- recipe_book — Recipe #20~23. 프론트: 내 레시피북(019)
CREATE TABLE cookbook.recipe_book (
  id          bigserial PRIMARY KEY,
  user_id     bigint NOT NULL,                -- ▶account.app_user 논리참조(크로스서비스·FK X)
  recipe_id   bigint REFERENCES data.recipe(id) ON DELETE SET NULL,  -- data (SAVED일 때). EXTRACTED/CUSTOM 본문 = 결정 #2
  source_type text NOT NULL CHECK (source_type IN ('SAVED','EXTRACTED','CUSTOM')),
  title       text NOT NULL,
  is_public   boolean NOT NULL DEFAULT false,
  share_token text UNIQUE,                    -- 공유 URL(#23)
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- recipe_extract_job — Recipe #24~25 (YouTube 추출, 비동기). 프론트: YouTube추출(020)
CREATE TABLE cookbook.recipe_extract_job (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,                 -- ▶account.app_user 논리참조(크로스서비스·FK X)
  url        text NOT NULL,
  status     text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','DONE','FAILED')),
  result     jsonb,                           -- 추출 재료·단계(저장 전 미리보기)
  created_at timestamptz NOT NULL DEFAULT now()
);

-- price_watch — Price #29~30 (최저가 관심). 멘토 피드백: 최저가 알림 fan-out 소스
CREATE TABLE price.price_watch (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,                 -- ▶account.app_user 논리참조(크로스서비스·FK X)
  item_id    bigint NOT NULL REFERENCES data.item_master(item_id) ON DELETE CASCADE,  -- data (품목 단위 관심)
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, item_id)                   -- item_id가 data FK로 확정 → 활성화
);

-- notification — Notification #41~42. 프론트: 알림함(017)·드롭다운/바텀시트
-- emoji/iconBg/to(딥링크)는 프론트가 type으로 파생 — 미저장.
CREATE TABLE notify.notification (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,                 -- ▶account.app_user 논리참조(크로스서비스·FK X)
  type       text NOT NULL CHECK (type IN ('LOW_PRICE','EXPIRING','HOTDEAL','BUDGET')),
  title      text NOT NULL,
  body       text,
  payload    jsonb,                           -- {item_id, recipe_id, deal_id…} 딥링크 데이터
  is_read    boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON notify.notification (user_id, is_read, created_at DESC);

-- notification_setting — Notification #43~44 (유저당 1행). 결정 필요 #5
CREATE TABLE notify.notification_setting (
  user_id    bigint PRIMARY KEY,              -- ▶account.app_user 논리참조(PK=user_id, 크로스서비스·FK X)
  low_price  boolean NOT NULL DEFAULT true,
  expiry     boolean NOT NULL DEFAULT true,
  hotdeal    boolean NOT NULL DEFAULT true,
  budget     boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);
```

---

## 4. 데이터 티어 조인 지도 (진짜 FK — `data` 스키마)

`data` 스키마는 읽기전용 공용이라 아래는 **진짜 FK**(`ON DELETE SET NULL`, `price_watch`만 `CASCADE`).

| OLTP 컬럼 | → 데이터 티어 | 용도 |
|---|---|---|
| `pantry.pantry_item.item_id` · `pantry.ocr_receipt_item.item_id` · `price.price_watch.item_id` | `data.item_master` | 표준품목·영양·emoji 매핑 |
| `pantry.pantry_item` (storage + item) | `data.shelf_life_ref` | 소비기한 임박일 추정 (조인 SELECT) |
| `mealplan.cart_item.retail_product_id` | `data.retail_product` / `data.retail_price` | 현재가·매장·핫딜 |
| `mealplan.cart_item.recipe_id` · `cookbook.recipe_book.recipe_id` | `data.recipe` | 레시피 연결 |

> 크로스-서비스(`*.user_id`, `expense.receipt_id`)는 **FK 아님** — 논리 `bigint`. §1.2 참조.

---

## 5. api-spec 커버리지

| api-spec # | 엔드포인트 | 백킹 테이블 |
|---|---|---|
| 2~6 | `/api/auth/*` | `account.app_user` |
| 7~8 | `/api/users/me` | `account.app_user` |
| 9~10 | `/api/users/budget` | `account.user_budget` |
| 11~15 | `/api/pantry/items`·`/expiring` | `pantry.pantry_item` |
| 16~17 | `/api/pantry/ocr` | `pantry.ocr_receipt`·`ocr_receipt_item` |
| 20~23 | `/api/recipes/book` | `cookbook.recipe_book` |
| 24~25 | `/api/recipes/extract` | `cookbook.recipe_extract_job` |
| 29~30 | `/api/prices/watch` | `price.price_watch` |
| 33~36 | `/api/mealplan/cart` | `mealplan.cart_item` (+ `expense` on checkout) |
| 38~40 | `/api/expenses/*` | `mealplan.expense` |
| 41~42 | `/api/notifications` | `notify.notification` |
| 43~44 | `/api/notifications/settings` | `notify.notification_setting` |

**테이블 불필요(stateless/데이터 티어):** #18~19 레시피 검색·상세(`data.recipe*`), #26~28·31 시세·핫딜(`data.price_*`·`retail_*`), #32 추천(계산), #37 어시스턴트(RAG), #45~47 ML 내부.

---

## 6. 결정 필요 (담당자 확정)

1. ~~**OLTP DB 분리 여부**~~ → **확정(2026-07-15): 스키마-퍼-서비스(단일 PG) + `data` 공용읽기.** §1 반영. 크로스-서비스=논리값, `data`참조=진짜 FK.
2. **유저 레시피 저장 위치** — YouTube추출/직접작성분을 `data.recipe`에 `source='USER'` 확장 vs 별도 `cookbook.user_recipe` 테이블. 초안은 `recipe_book.source_type`만 두고 본문은 유보. *(추천: 별도 `cookbook.user_recipe` — 크롤 카탈로그 `data.recipe`의 품질게이트/ES 재색인 오염 방지.)*
3. **OCR 파싱 결과 형태** — 정규화 `ocr_receipt_item`(초안) vs `ocr_receipt.result jsonb` 단일 컬럼.
4. **장바구니 범위** — 유저당 단일 active cart(초안, 간단) vs cart 헤더 + 주문 이력(`shopping_order`) 유지.
5. **알림 설정 위치** — 별도 `notification_setting`(초안) vs `app_user` 컬럼 인라인.
6. **가격 스냅샷** — `cart_item` 담을 때 가격 고정 vs 항상 실시간 조회(초안).
7. **`meal_plan` 저장 필요 여부** — `POST /mealplan/recommend`가 stateless면 불필요(초안엔 없음). "며칠치 플랜" 영속화가 필요하면 추가.
8. **(신규) Expense·Notification 서비스 경계** — `design.md §5`는 서비스 8개, `api-spec.md`는 Expense·Notification을 갈라 10개로 셈. 위 스키마는 Expense를 `mealplan`에, Notification을 독립 `notify`에 배치. 독립 배포 단위로 뗄지 미정.

---

## 7. 다음 단계

1. §6 #2~7(+#8) 확정 → 이 문서 반영
2. 확정본을 `schema-app-oltp.sql`(적용용 DDL: `CREATE SCHEMA` + role/GRANT + 테이블)로 구현 + `apply_schema.py` 계열로 멱등 적용
3. `data` 스키마 마이그레이션(현 `public` → `data` 이동 or `public` 공용읽기 GRANT) 소소 처리
4. `api-spec.md`의 해당 엔드포인트 **응답 스키마 상세화**(필드·타입)를 이 테이블 기준으로 채움
5. 프론트 `mock.ts` → 실제 응답 shape로 정렬 후 TanStack Query 훅 연동
