-- schema-production.sql — 앱 OLTP 프로덕션 스키마 (멱등 DDL)
-- SSOT: docs/prd/schema-production.md
--
-- 데이터 티어(item_master·recipe·retail_*·food_nutrition·price_*·shelf_life_ref)는 현재 `public`.
--   문서의 `data.*`는 이전 목표 — 현재는 `public.*` 참조. (public→data 이전 시 일괄 치환.)
-- 역할/GRANT(서비스별 격리)는 비밀번호가 필요한 별도 보안 단계 → schema-production.md §0.3 참조. 이 파일엔 없음.
-- 멱등: CREATE ... IF NOT EXISTS. 재실행 안전(단 컬럼 변경은 IF NOT EXISTS로 반영 안 됨 — 스키마 변경 시 마이그레이션 별도).

CREATE SCHEMA IF NOT EXISTS account;
CREATE SCHEMA IF NOT EXISTS recipebook;
CREATE SCHEMA IF NOT EXISTS pantry;
CREATE SCHEMA IF NOT EXISTS mealplan;
CREATE SCHEMA IF NOT EXISTS price;
CREATE SCHEMA IF NOT EXISTS notify;

-- ==================== account (Auth + User) ====================
CREATE TABLE IF NOT EXISTS account.app_user (
  id            bigserial PRIMARY KEY,
  email         text UNIQUE,
  password_hash text,
  nickname      text NOT NULL,
  provider      text NOT NULL DEFAULT 'local' CHECK (provider IN ('local','kakao')),
  provider_uid  text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (provider, provider_uid)
);

CREATE TABLE IF NOT EXISTS account.user_budget (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL REFERENCES account.app_user(id) ON DELETE CASCADE,
  month      date NOT NULL,
  amount     numeric NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, month)
);

-- ==================== recipebook (RecipeBook) ====================
CREATE TABLE IF NOT EXISTS recipebook.bookmark (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,                                              -- 논리값(크로스서비스)
  recipe_id  bigint NOT NULL REFERENCES public.recipe(id) ON DELETE CASCADE,  -- 카탈로그 포인터
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, recipe_id)
);
CREATE INDEX IF NOT EXISTS bookmark_user_created_idx ON recipebook.bookmark (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS recipebook.user_recipe (
  id          bigserial PRIMARY KEY,
  user_id     bigint NOT NULL,
  origin      text NOT NULL CHECK (origin IN ('MANUAL','YOUTUBE')),
  title       text NOT NULL,
  source_url  text,
  image_url   text,
  ingredients jsonb,
  steps       jsonb,
  is_public   boolean NOT NULL DEFAULT false,
  share_token text UNIQUE,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS user_recipe_user_created_idx ON recipebook.user_recipe (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS recipebook.extract_job (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,
  url        text NOT NULL,
  status     text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','DONE','FAILED')),
  result     jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ==================== pantry (Pantry) ====================
CREATE TABLE IF NOT EXISTS pantry.pantry_item (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,
  item_id    bigint REFERENCES public.item_master(item_id) ON DELETE SET NULL,
  name       text NOT NULL,
  quantity   text,
  storage    text NOT NULL CHECK (storage IN ('ROOM','FRIDGE','FREEZER')),
  expire_at  date,                                                         -- 소비기한 추정 or 유저입력
  source     text NOT NULL DEFAULT 'MANUAL' CHECK (source IN ('MANUAL','OCR')),
  status     text NOT NULL DEFAULT 'ACTIVE'  CHECK (status IN ('ACTIVE','CONSUMED','DISCARDED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  closed_at  timestamptz
);
CREATE INDEX IF NOT EXISTS pantry_item_user_status_idx ON pantry.pantry_item (user_id, status);
CREATE INDEX IF NOT EXISTS pantry_item_user_expire_idx ON pantry.pantry_item (user_id, expire_at);

CREATE TABLE IF NOT EXISTS pantry.ocr_receipt (
  id           bigserial PRIMARY KEY,
  user_id      bigint NOT NULL,
  status       text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','DONE','FAILED')),
  store        text,
  purchased_at timestamptz,
  total_amount numeric,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ocr_receipt_user_created_idx ON pantry.ocr_receipt (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS pantry.ocr_receipt_item (
  id          bigserial PRIMARY KEY,
  receipt_id  bigint NOT NULL REFERENCES pantry.ocr_receipt(id) ON DELETE CASCADE,
  raw_text    text,
  name        text,
  item_id     bigint REFERENCES public.item_master(item_id) ON DELETE SET NULL,
  quantity    text,
  price       numeric,
  is_food     boolean NOT NULL DEFAULT true,
  confirmed   boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS ocr_receipt_item_receipt_idx ON pantry.ocr_receipt_item (receipt_id);

-- ==================== mealplan (MealPlan + Expense) ====================
CREATE TABLE IF NOT EXISTS mealplan.cart_item (
  id                bigserial PRIMARY KEY,
  user_id           bigint NOT NULL,
  retail_product_id bigint REFERENCES public.retail_product(id)   ON DELETE SET NULL,
  recipe_id         bigint REFERENCES public.recipe(id)           ON DELETE SET NULL,
  item_id           bigint REFERENCES public.item_master(item_id) ON DELETE SET NULL,
  name              text NOT NULL,
  qty               int NOT NULL DEFAULT 1,
  quantity          text,
  added_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cart_item_user_idx ON mealplan.cart_item (user_id);

CREATE TABLE IF NOT EXISTS mealplan.expense (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,
  amount     numeric NOT NULL,
  category   text NOT NULL CHECK (category IN ('GROCERY','DINING','DELIVERY','ETC')),
  spent_on   date NOT NULL,
  memo       text,
  source     text NOT NULL DEFAULT 'MANUAL' CHECK (source IN ('MANUAL','OCR','CART')),
  receipt_id bigint,                                                       -- ▶pantry.ocr_receipt 논리값(FK X)
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS expense_user_spenton_idx ON mealplan.expense (user_id, spent_on);

-- ==================== price (Price) ====================
CREATE TABLE IF NOT EXISTS price.price_watch (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,
  item_id    bigint NOT NULL REFERENCES public.item_master(item_id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, item_id)
);
CREATE INDEX IF NOT EXISTS price_watch_item_idx ON price.price_watch (item_id);   -- fan-out 역조회

-- ==================== notify (Notification) ====================
CREATE TABLE IF NOT EXISTS notify.notification (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL,
  type       text NOT NULL CHECK (type IN ('LOW_PRICE','EXPIRING','HOTDEAL','BUDGET')),
  title      text NOT NULL,
  body       text,
  payload    jsonb,
  is_read    boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS notification_user_unread_idx ON notify.notification (user_id, is_read, created_at DESC);

CREATE TABLE IF NOT EXISTS notify.notification_setting (
  user_id    bigint PRIMARY KEY,
  low_price  boolean NOT NULL DEFAULT true,
  expiry     boolean NOT NULL DEFAULT true,
  hotdeal    boolean NOT NULL DEFAULT true,
  budget     boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);
