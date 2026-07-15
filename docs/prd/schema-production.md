# 프로덕션 스키마 (확정본) — food-budget-app 앱 OLTP

> **SSOT.** 이 문서가 앱 OLTP(유저 쓰기) 스키마의 **단일 소스 오브 트루스**다 (2026-07-15 결정). 앞으로 스키마 작업·확정은 전부 여기에 기록한다. [`schema-app-oltp.md`](./schema-app-oltp.md)는 **참고용 초안**(설계 논의 이력 — 더 이상 정본 아님·수정 안 함), 크롤·공공 읽기 소스는 [`schema-public-data.sql`](./schema-public-data.sql)(데이터 티어).
>
> **위치 = 하이브리드** (초안 §1): 경계는 MSA(서비스별 스키마 소유 · role 격리 · 크로스-서비스 FK 없음 → `user_id`는 JWT 값), 물리는 모놀리스(단일 PostgreSQL DB · 공유 읽기 `data` 스키마에만 진짜 FK).
>
> 확정 스키마는 **여기가 정본**이며 초안의 해당 섹션을 대체한다.

---

## 0. 공통 규칙

### 0.1 컨벤션 (초안 §2와 동일)
- PK `bigserial` · 시각 `timestamptz NOT NULL DEFAULT now()` · 이름 `snake_case`
- enum = `text ... CHECK (col IN (...))` · 금액 = `numeric`(KRW)
- 프론트 파생값(`₩`·D-day·`%`·emoji)은 **미저장** — 서버는 원시값만

### 0.2 FK 정책 (초안 §1.2)
| 참조 종류 | 정책 |
|---|---|
| 같은 스키마 내 | **진짜 FK** (+ CASCADE) |
| 크로스-서비스(→ 다른 서비스 스키마) | **FK 없음 · 논리 `bigint`** (JWT의 `user_id` 신뢰) |
| → `data` 스키마 (공용 읽기) | **진짜 FK** (`ON DELETE SET NULL`, 단 순수 포인터는 `CASCADE`) |

> 크로스-서비스 FK가 없으므로 **유저 삭제 시 DB CASCADE가 안 됨** → 각 서비스가 탈퇴 정리(동기 `/internal` 호출 or 소프트삭제+배치)를 앱 레벨에서 담당.

### 0.3 스키마 + role 셋업 (확정분)
```sql
CREATE SCHEMA IF NOT EXISTS account;
CREATE SCHEMA IF NOT EXISTS recipebook;
CREATE SCHEMA IF NOT EXISTS pantry;
CREATE SCHEMA IF NOT EXISTS mealplan;
CREATE SCHEMA IF NOT EXISTS price;
CREATE SCHEMA IF NOT EXISTS notify;
-- data 스키마 = 기존 데이터 티어(읽기전용 공용)

-- account 서비스 role (data 티어 안 읽음)
CREATE ROLE svc_account LOGIN PASSWORD :'account_pw';
GRANT USAGE, CREATE ON SCHEMA account TO svc_account;

-- recipebook 서비스 role (data.recipe 읽음)
CREATE ROLE svc_recipebook LOGIN PASSWORD :'recipebook_pw';
GRANT USAGE, CREATE ON SCHEMA recipebook TO svc_recipebook;
GRANT USAGE  ON SCHEMA data TO svc_recipebook;
GRANT SELECT ON ALL TABLES IN SCHEMA data TO svc_recipebook;
ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT ON TABLES TO svc_recipebook;

-- pantry 서비스 role (data.item_master·shelf_life_ref 읽음)
CREATE ROLE svc_pantry LOGIN PASSWORD :'pantry_pw';
GRANT USAGE, CREATE ON SCHEMA pantry TO svc_pantry;
GRANT USAGE  ON SCHEMA data TO svc_pantry;
GRANT SELECT ON ALL TABLES IN SCHEMA data TO svc_pantry;
ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT ON TABLES TO svc_pantry;

-- mealplan 서비스 role (data 전반: recipe·retail·item_master + 공공 food_nutrition·price_online_daily)
CREATE ROLE svc_mealplan LOGIN PASSWORD :'mealplan_pw';
GRANT USAGE, CREATE ON SCHEMA mealplan TO svc_mealplan;
GRANT USAGE  ON SCHEMA data TO svc_mealplan;
GRANT SELECT ON ALL TABLES IN SCHEMA data TO svc_mealplan;
ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT ON TABLES TO svc_mealplan;

-- price 서비스 role (data 읽기: retail_*·price_*·item_master)
CREATE ROLE svc_price LOGIN PASSWORD :'price_pw';
GRANT USAGE, CREATE ON SCHEMA price TO svc_price;
GRANT USAGE  ON SCHEMA data TO svc_price;
GRANT SELECT ON ALL TABLES IN SCHEMA data TO svc_price;
ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT ON TABLES TO svc_price;

-- notify 서비스 role (data 안 읽음 — 생성 서비스가 title/body 완성해 전달)
CREATE ROLE svc_notify LOGIN PASSWORD :'notify_pw';
GRANT USAGE, CREATE ON SCHEMA notify TO svc_notify;
-- 각 role은 서로의 스키마에 GRANT 없음 → PostgreSQL 기본 거부로 크로스서비스 자동 차단.
```

### 0.4 확정 현황
| 스키마 | 서비스 | 상태 |
|---|---|---|
| `account` | Auth + User | ✅ **확정** (아래 §1) |
| `recipebook` | RecipeBook | ✅ **확정** (아래 §2) |
| `pantry` | Pantry | ✅ **확정** (아래 §3) |
| `mealplan` | MealPlan + Expense | ✅ **확정** (아래 §4) |
| `price` | Price | ✅ **확정** (아래 §5) |
| `notify` | Notification | ✅ **확정** (아래 §6) |

### 0.5 `data` 스키마(공용 읽기) 범위 — 크롤 + 공공데이터 전부
서비스는 필요 시 `data`의 **모든** 테이블을 SELECT(`GRANT SELECT ON ALL TABLES`). 크롤분만이 아니라 **공공데이터 포함**:
- **크롤**: `item_master`·`item_alias`(품목 스파인) · `recipe`(+`_ingredient`·`_step`) · `retail_product`·`retail_price`(+뷰)
- **공공**: `food_nutrition`(**영양성분**) · `price_item`·`price_online_daily`(**온라인가격**·시세 baseline) · `shelf_life_ref`(**소비기한**)

참조 예: 영양성분 = Recipe·RecipeBook·MealPlan · 온라인가격 baseline = Price·MealPlan · 소비기한 = Pantry.

---

## 1. `account` 스키마 — Auth + User

**서비스:** 로그인·JWT 발급/검증(Auth) + 프로필·월 예산(User). `app_user`를 공유하므로 한 스키마. **신원의 뿌리** — login/kakao가 여기서 자격증명을 검증하고 `user_id`를 JWT에 실어 나머지 서비스로 전파. (api-spec #2~10)

```sql
-- app_user — Auth #2~6, User #7~8
CREATE TABLE account.app_user (
  id            bigserial PRIMARY KEY,
  email         text UNIQUE,                 -- 카카오 전용이면 null
  password_hash text,                        -- 자체 로그인만; 카카오면 null
  nickname      text NOT NULL,
  provider      text NOT NULL DEFAULT 'local' CHECK (provider IN ('local','kakao')),
  provider_uid  text,                        -- 카카오 회원번호
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (provider, provider_uid)
);

-- user_budget — User #9~10 (월 예산). 프론트: 예산설정·홈 히어로·식비 요약
CREATE TABLE account.user_budget (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL REFERENCES account.app_user(id) ON DELETE CASCADE,  -- 같은 스키마 → FK
  month      date NOT NULL,                  -- 매월 1일로 정규화 (예: 2026-07-01)
  amount     numeric NOT NULL,               -- 월 예산액(KRW)
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, month)
);
```

**메모**
- `email`·`password_hash` nullable, `provider_uid` = 카카오 식별자 → 로컬/카카오를 `provider`+`UNIQUE(provider,provider_uid)`로 구분(카카오 재로그인 upsert).
- 예산을 `app_user` 컬럼이 아니라 **월별 행**으로 둠 → 지난달 대비·성과지표용 시계열. `GET budget` = `month = date_trunc('month', now())`.
- **`user_budget.user_id`가 유일하게 진짜 FK인 곳**(같은 스키마·같은 서비스). 다른 스키마의 `user_id`는 전부 논리값.

---

## 2. `recipebook` 스키마 — RecipeBook (유저)

**서비스:** 유저가 **북마크/직접작성/유튜브추출**로 레시피를 개인 저장. (api-spec #20~25)

> ⚠️ **"Recipe(카탈로그)" 서비스와 구분:** 만개레시피 크롤분을 나열·검색·제공하는 Recipe 서비스는 `data.recipe*`만 읽는 **읽기전용·write 0** 서비스(유저 데이터 아님, #18·#19). RecipeBook만 유저 쓰기 데이터를 소유한다.
>
> 이 스키마는 초안 §3.5의 `cookbook`(polymorphic `recipe_book`+`user_recipe`)을 **대체**한다. 근거: 북마크(카탈로그 포인터)와 유저 레시피(본문 콘텐츠)는 성격이 근본적으로 달라 테이블을 분리하는 게 명확. → **초안 결정 #2 해소**(유저 콘텐츠는 카탈로그와 분리).

```sql
-- bookmark — 카탈로그 레시피를 내 레시피북에 저장 (포인터, 본문 복사 X). #20~22
CREATE TABLE recipebook.bookmark (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,                                          -- 논리값(크로스서비스·FK X)
  recipe_id  bigint NOT NULL REFERENCES data.recipe(id) ON DELETE CASCADE,  -- 카탈로그 포인터(순수 포인터라 CASCADE)
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, recipe_id)                                          -- 같은 레시피 중복 북마크 방지
);
CREATE INDEX ON recipebook.bookmark (user_id, created_at DESC);

-- user_recipe — 유저 소유 레시피(수동 작성 or 유튜브 추출). 카탈로그에 없는 콘텐츠. 공유 가능. #21·#24~25
CREATE TABLE recipebook.user_recipe (
  id          bigserial PRIMARY KEY,
  user_id     bigint NOT NULL,                                         -- 논리값
  origin      text NOT NULL CHECK (origin IN ('MANUAL','YOUTUBE')),
  title       text NOT NULL,
  source_url  text,                                                    -- YOUTUBE면 원본 URL
  image_url   text,
  ingredients jsonb,                                                   -- [{name, quantity, item_id?}] (NER 결과)
  steps       jsonb,                                                   -- [{step_no, description, image_url?}]
  is_public   boolean NOT NULL DEFAULT false,
  share_token text UNIQUE,                                             -- 공유 URL(#23) — 유저 레시피만 공유
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON recipebook.user_recipe (user_id, created_at DESC);

-- extract_job — 유튜브 추출 비동기 job(접수→폴링→확정). #24~25
CREATE TABLE recipebook.extract_job (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,                                          -- 논리값
  url        text NOT NULL,
  status     text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','DONE','FAILED')),
  result     jsonb,                                                    -- 추출 미리보기(재료·단계)
  created_at timestamptz NOT NULL DEFAULT now()
);
```

**메모**
- **`bookmark` = 포인터, `user_recipe` = 본문.** 북마크는 카탈로그(`data.recipe`)를 가리키기만 하고 본문을 복사하지 않음(중복·stale 방지). 직접작성/유튜브추출은 카탈로그에 없는 유저 콘텐츠라 본문을 `user_recipe`에 저장.
- **"내 레시피북 목록"(#20) = `bookmark` ∪ `user_recipe`** (UNION 뷰 or 앱 병합). 저볼륨이라 무해, 대신 각 테이블이 단일 목적이라 명확.
- **공유는 `user_recipe`에만**(`is_public`/`share_token`). 북마크는 사적 저장 — 카탈로그 레시피는 이미 Recipe 서비스로 공개.
- **FK 대조:** `bookmark.recipe_id`는 순수 포인터라 `CASCADE`(카탈로그 사라지면 북마크도 무의미). `data`행에 스냅샷을 함께 쥔 참조(예: 다른 스키마의 `cart_item.name`)는 `SET NULL`.
- **비동기 job:** `extract_job`은 pantry의 영수증 OCR과 같은 접수→폴링 패턴. `DONE` → 유저 확정 → `user_recipe(origin='YOUTUBE')` 생성.
- 본문을 `jsonb`로 둔 이유: 유저 레시피는 통째로 읽고/편집하는 단위라 정규화 테이블 대신 `jsonb`로 스키마를 작게. 재료별 가격매핑 필요 시 `jsonb` 원소에 `item_id`를 심음.

---

## 3. `pantry` 스키마 — Pantry

**서비스:** 냉장고 재고 관리 + **소비기한(추정) 임박 알림** + 영수증 OCR 입력. (api-spec #11~17)

```sql
-- pantry_item — 냉장고 재고 한 줄. #11~15
CREATE TABLE pantry.pantry_item (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,                                          -- 논리값(크로스서비스·FK X)
  item_id    bigint REFERENCES data.item_master(item_id) ON DELETE SET NULL,  -- 표준품목·영양·emoji
  name       text NOT NULL,                                            -- 표시명(원문/수기)
  quantity   text,                                                     -- '1단','500g','8구' (표시용, 산술 X)
  storage    text NOT NULL CHECK (storage IN ('ROOM','FRIDGE','FREEZER')),
  expire_at  date,                                                     -- 소비기한 추정(shelf_life_ref 보관수명) or 유저입력
  source     text NOT NULL DEFAULT 'MANUAL' CHECK (source IN ('MANUAL','OCR')),
  status     text NOT NULL DEFAULT 'ACTIVE'  CHECK (status IN ('ACTIVE','CONSUMED','DISCARDED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  closed_at  timestamptz                                              -- 소진/폐기 시각 → '안 버린 재료 %'
);
CREATE INDEX ON pantry.pantry_item (user_id, status);
CREATE INDEX ON pantry.pantry_item (user_id, expire_at);

-- ocr_receipt / ocr_receipt_item — 영수증 OCR(비동기). #16~17
CREATE TABLE pantry.ocr_receipt (
  id           bigserial PRIMARY KEY,
  user_id      bigint NOT NULL,                                        -- 논리값
  status       text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','DONE','FAILED')),
  store        text,                                                   -- 인식 매장명
  purchased_at timestamptz,
  total_amount numeric,
  created_at   timestamptz NOT NULL DEFAULT now()
  -- 원본 이미지는 미저장(분석에만 사용).
);
CREATE TABLE pantry.ocr_receipt_item (
  id          bigserial PRIMARY KEY,
  receipt_id  bigint NOT NULL REFERENCES ocr_receipt(id) ON DELETE CASCADE,  -- 같은 스키마 → FK
  raw_text    text,                                                    -- '삼겹500'
  name        text,                                                    -- '돼지고기 삼겹살'
  item_id     bigint REFERENCES data.item_master(item_id) ON DELETE SET NULL,  -- NER 결과
  quantity    text,
  price       numeric,
  is_food     boolean NOT NULL DEFAULT true,                           -- '봉투' 등 제외
  confirmed   boolean NOT NULL DEFAULT false
);
CREATE INDEX ON pantry.ocr_receipt (user_id, created_at DESC);
CREATE INDEX ON pantry.ocr_receipt_item (receipt_id);
```

**메모**
- **`item_id` = data FK(SET NULL)** — 표준품목에 붙으면 영양·emoji·소비기한추정이 딸려옴. 매칭 실패해도 `name`으로 표시 → nullable. (순수 포인터인 `bookmark`는 CASCADE, 여기는 `name` 스냅샷이 남아 SET NULL.)
- **소비기한(추정)은 JOIN, FK 아님** — 용어는 **소비기한**(2023 소비기한→소비기한 개정); 값은 패키지 라벨이 아니라 **`담은날 + 보관수명`** 추정. `expire_at` 없으면 추가 시 `(item_id, storage)`로 `data.shelf_life_ref`(보관수명 days)를 조인해 계산 → 구체 `date`로 저장(유저 override). FK 컬럼 안 둠(질의 시 조인).
  - ⚠️ **커버리지 현실**: `shelf_life_ref` 1,264행 중 **item_id 앵커는 CURATED 153행뿐**(FoodKeeper 1,111행은 영어명·미앵커라 한국 재료 자동추정에 미사용). 따라서 `item_id` 자동추정은 **~153품목만 커버**, 나머지는 유저입력. 커버리지 확대는 곧 큐레이션(FoodKeeper 앵커링) 작업.
- **`quantity`는 text(표시용)** — 재고는 산술 안 함 → cart_item과 달리 numeric 불필요. *숫자는 산술하는 곳에만.*
- **성과지표 '안 버린 재료 %'** — 제거 시 하드삭제 대신 `status`=CONSUMED(먹음)/DISCARDED(버림) + `closed_at` → `consumed / (consumed+discarded)`. 상태전이는 #13 PATCH, #14 DELETE는 오입력 정정용 하드삭제로만. idx `(user_id,status)`가 ACTIVE 필터 + 성과 집계 커버, `(user_id,expire_at)`가 임박(#15).
- **영수증 1:N + 크로스서비스** — `ocr_receipt`→`ocr_receipt_item` 진짜 FK(CASCADE). DONE → 유저 확정 → `pantry_item` 생성 + **`mealplan.expense`는 MealPlan API 호출로 생성**(남의 스키마에 직접 못 씀 = MSA 경계). 원본 영수증 이미지 미저장.

---

## 4. `mealplan` 스키마 — MealPlan (+ Expense 병합)

**서비스:** 예산 밀플래닝(추천·어시스턴트) + 장바구니 + 캘린더 식비추적 + 성과지표. **오케스트레이터** — 예산(account)·냉장고(pantry)·레시피/가격/영양(data)을 끌어씀. (api-spec #32~40)

> **Expense 병합 확정(2026-07-15, 초안 #8 해소):** Expense를 별도 서비스로 안 뗌. 근거 = checkout(#36)이 `cart_item 삭제 + expense 생성` **한 트랜잭션**이라 같은 서비스·스키마라야 원자적. 식비추적이 독립적으로 커지면 §1.4 방식으로 승격.

```sql
-- cart_item — 유저당 단일 active 장바구니. 가격 미저장(실시간 조회). #33~36
CREATE TABLE mealplan.cart_item (
  id                bigserial PRIMARY KEY,
  user_id           bigint NOT NULL,                                        -- 논리값(크로스서비스·FK X)
  retail_product_id bigint REFERENCES data.retail_product(id)   ON DELETE SET NULL,  -- 특정 SKU(현재가·매장)
  recipe_id         bigint REFERENCES data.recipe(id)           ON DELETE SET NULL,  -- 출처 레시피
  item_id           bigint REFERENCES data.item_master(item_id) ON DELETE SET NULL,  -- 품목(최저가 비교)
  name              text NOT NULL,                                          -- 스냅샷 표시명
  qty               int NOT NULL DEFAULT 1,                                 -- 팩 개수(계산: total=Σ단가×qty)
  quantity          text,                                                   -- 표시용 원문('2개','1단')
  added_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON mealplan.cart_item (user_id);

-- expense — 식비 한 건. 캘린더·성과의 원천. #38~40 + checkout 자동생성
CREATE TABLE mealplan.expense (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,                                              -- 논리값
  amount     numeric NOT NULL,
  category   text NOT NULL CHECK (category IN ('GROCERY','DINING','DELIVERY','ETC')),  -- 장보기/외식/배달/기타
  spent_on   date NOT NULL,                                                -- 캘린더 집계 키
  memo       text,
  source     text NOT NULL DEFAULT 'MANUAL' CHECK (source IN ('MANUAL','OCR','CART')),
  receipt_id bigint,                                                       -- ▶pantry.ocr_receipt 논리값(크로스서비스·FK X)
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON mealplan.expense (user_id, spent_on);
```

**메모**
- **cart_item = "무엇"만, 가격 미저장** — 결정 #6(실시간 조회). `qty`(int,계산) vs `quantity`(text,표시). 가격 정본 = `data.retail_price`.
- **data FK 3경로** — `retail_product_id`(특정 SKU) / `item_id`(품목·최저가 비교) / `recipe_id`(출처). 레시피에서 담으면 recipe_id+item_id 공존 정상 → xor CHECK 없음. 셋 다 `SET NULL`(스냅샷 `name` 유지).
- **부족재료 담기(#34)** — 레시피 선택 시 `data.recipe_ingredient`(SQL) − 냉장고 보유(**Pantry API**)를 **item_id 기준 차집합** → 사야 할 것만 insert. 필터 기준 = 표준 품목 `item_id`(이름 아님). MVP는 presence만(수량 차감 P1), 미매칭(item_id NULL)은 안전하게 담기, ACTIVE만 보유로 카운트.
- **cart remain(#33)은 SQL+API 합성** — 장바구니합계=`cart_item ⋈ data.retail_unit_price`(SQL) / 기지출=`mealplan.expense`(자기 SQL) / **예산=`account.user_budget`는 User API**(mealplan은 account 스키마 GRANT 없음). remain은 앱에서 합성.
- **checkout(#36)=원자 트랜잭션** — cart 비우고 `expense(source='CART')` 생성이 같은 스키마라 한 트랜잭션. (대조: OCR→expense는 Pantry가 MealPlan API 호출 = 크로스서비스.)
- **expense** — `source`(MANUAL 외식/OCR 영수증/CART 장보기)·`category`·`spent_on`(캘린더 키, idx). `receipt_id`는 `pantry.ocr_receipt` 논리값(크로스서비스·FK X).
- **공공데이터 참조** — mealplan은 `data`의 크롤분(retail_*·recipe*) 외에 **공공데이터도 필요 시 SELECT**: `food_nutrition`(영양성분 — 추천·플랜 영양), `price_online_daily`(온라인가격 — 시세 baseline). §0.5 참조.
- **#40 성과지표 = 크로스서비스 합성** — 예산(User API) + 기지출(자기 SQL) + 안버린재료(Pantry API).

---

## 5. `price` 스키마 — Price

**서비스:** 현재가·이력·시세추천·핫딜(전부 `data` 읽기) + 최저가 관심 등록. **얇은 write, 두꺼운 read** — 6 엔드포인트 중 write는 `price_watch` 하나뿐. (api-spec #26~31)

```sql
-- price_watch — 최저가 관심(품목 단위). 최저가 알림 fan-out 소스(멘토 피드백 §8.2 다자간). #29~30
CREATE TABLE price.price_watch (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,                                              -- 논리값
  item_id    bigint NOT NULL REFERENCES data.item_master(item_id) ON DELETE CASCADE,  -- 품목 대상
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, item_id)                                                -- 중복 관심 방지 + 정방향 인덱스
);
CREATE INDEX ON price.price_watch (item_id);   -- fan-out: 이 품목 관심자 전원 역조회
```

**메모**
- **관심은 품목(`item_id`) 단위** — 유저는 "대파 싸지면"이지 특정 SKU가 아님. 품목 없으면 watch 무의미 → `NOT NULL`·`CASCADE`. 최저가 값 자체는 `data.retail_item_price_compare` 실시간.
- **fan-out은 역방향 조회** — 이상탐지 "대파 급락" → `WHERE item_id=? → 관심자 user_id[]` → `notify.notification` fan-out(Kafka·KEDA, §7.1 Kafka 2용도 중 하나). `UNIQUE(user_id,item_id)`가 정방향(내 목록), **별도 `idx(item_id)`가 역방향(관심자 전원)** 을 커버.
- #26~28·31(현재가·이력·시세·핫딜)은 write 테이블 없음 — `data.retail_*`·`price_*` 조회. §0.5의 온라인가격 baseline(`price_online_daily`)도 여기서 참조.

---

## 6. `notify` 스키마 — Notification (cross-cutting)

**서비스:** 알림함 + 설정. 알림은 어느 도메인 것도 아니라 **여러 서비스가 생성**(Price=LOW_PRICE·HOTDEAL, Pantry=EXPIRING, MealPlan=BUDGET) → 다른 서비스는 **notify API 호출로 생성**(남의 스키마 직접 쓰기 X). (api-spec #41~44)

```sql
-- notification — 알림 1건. 여러 서비스가 notify API로 생성. #41~42
CREATE TABLE notify.notification (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,                                              -- 논리값
  type       text NOT NULL CHECK (type IN ('LOW_PRICE','EXPIRING','HOTDEAL','BUDGET')),
  title      text NOT NULL,
  body       text,
  payload    jsonb,                                                        -- {item_id, recipe_id, deal_id…} 딥링크
  is_read    boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON notify.notification (user_id, is_read, created_at DESC);

-- notification_setting — 유저당 1행. #43~44
CREATE TABLE notify.notification_setting (
  user_id    bigint PRIMARY KEY,                                           -- 논리값(PK=user_id)
  low_price  boolean NOT NULL DEFAULT true,
  expiry     boolean NOT NULL DEFAULT true,
  hotdeal    boolean NOT NULL DEFAULT true,
  budget     boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);
```

**메모**
- **notify는 `data`를 안 읽음** — `title`/`body`는 생성 서비스가 완성해 전달(Price가 "대파가 최저가!" 조립). notify는 저장·조회만 → `svc_notify`는 data GRANT 없음(`account`과 함께 유이하게 data 미참조).
- `type`이 생성 서비스를 암시 · `payload jsonb`=딥링크(탭→화면) · emoji/아이콘은 프론트가 `type`으로 파생(미저장).
- 복합 idx `(user_id, is_read, created_at DESC)`가 알림함 "내 것·안읽음 우선·최신순"(#41 `?unread=`)을 한 방에. 설정은 유저당 1행 → `user_id`가 PK.
- **알림 발송 전 설정 확인은 notify 내부** — 생성 요청 시 `notification_setting`의 해당 type이 off면 스킵(또는 저장하되 push 안 함).

---

## ✅ 앱 OLTP 스키마 6개 전부 확정 (2026-07-15)
`account` · `recipebook` · `pantry` · `mealplan`(+Expense) · `price` · `notify`. 데이터 티어(`data`)는 크롤+공공 읽기 소스(§0.5).

**다음 단계:** ① 이 문서를 `schema-production.sql`(멱등 DDL: CREATE SCHEMA + role/GRANT + 테이블)로 구현 → `apply_schema.py` 계열로 적용 · ② `public`→`data` 스키마 마이그레이션(소소) · ③ `api-spec.md` 응답 스키마 상세화 · ④ 프론트 `mock.ts` 정렬.
