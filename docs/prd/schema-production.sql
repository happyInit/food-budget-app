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
CREATE SCHEMA IF NOT EXISTS chat;
CREATE SCHEMA IF NOT EXISTS activity;

-- ==================== account (Auth + User) ====================
CREATE TABLE IF NOT EXISTS account.app_user (
  id            bigserial PRIMARY KEY,
  email         text UNIQUE,
  password_hash text,
  nickname      text NOT NULL,
  provider      text NOT NULL DEFAULT 'local' CHECK (provider IN ('local','kakao','google')),
  provider_uid  text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  activity_consent boolean NOT NULL DEFAULT false,   -- 유저 데이터 수집 동의(클릭스트림+챗대화 통합, D-2). opt-in
  consented_at     timestamptz,                       -- 동의 시각(철회 시 NULL)
  UNIQUE (provider, provider_uid)
);
-- 기존 DB 반영 — CREATE IF NOT EXISTS는 컬럼 미추가라 멱등 ALTER 별도(D-2 동의 게이팅)
ALTER TABLE account.app_user ADD COLUMN IF NOT EXISTS activity_consent boolean NOT NULL DEFAULT false;
ALTER TABLE account.app_user ADD COLUMN IF NOT EXISTS consented_at     timestamptz;
-- provider CHECK 확장(google 소셜 로그인) — 인라인 CHECK 는 기존 DB 에 반영 안 되므로 멱등 재정의.
--   인라인 컬럼 CHECK 의 자동 이름 = <table>_<column>_check = app_user_provider_check.
ALTER TABLE account.app_user DROP CONSTRAINT IF EXISTS app_user_provider_check;
ALTER TABLE account.app_user ADD CONSTRAINT app_user_provider_check CHECK (provider IN ('local','kakao','google'));

CREATE TABLE IF NOT EXISTS account.user_budget (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL REFERENCES account.app_user(id) ON DELETE CASCADE,
  month      date NOT NULL,
  amount     numeric NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, month)
);

-- 제외(회피) 재료 — 추천에서 이 표준품목이 든 레시피를 걸러낸다(mealplan recommend seam이 조회).
CREATE TABLE IF NOT EXISTS account.user_excluded_item (
  id         bigserial PRIMARY KEY,
  user_id    bigint NOT NULL REFERENCES account.app_user(id) ON DELETE CASCADE,
  item_id    bigint NOT NULL REFERENCES public.item_master(item_id) ON DELETE CASCADE,  -- 표준품목 포인터
  name       text NOT NULL,                                                             -- 표시명 스냅샷
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, item_id)
);
CREATE INDEX IF NOT EXISTS user_excluded_item_user_idx ON account.user_excluded_item (user_id);

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
  cooking_time text,                                                  -- 만개 레시피와 동일 메타(칩): '15분 이내'
  serving      text,                                                  -- '2인분'
  level_nm     text,                                                  -- '아무나' | '초급' | '중급'
  is_public   boolean NOT NULL DEFAULT false,
  share_token text UNIQUE,
  created_at  timestamptz NOT NULL DEFAULT now()
);
-- 기존 DB 증분 마이그레이션(멱등) — 위 컬럼 3종 뒤늦게 추가.
ALTER TABLE recipebook.user_recipe ADD COLUMN IF NOT EXISTS cooking_time text;
ALTER TABLE recipebook.user_recipe ADD COLUMN IF NOT EXISTS serving      text;
ALTER TABLE recipebook.user_recipe ADD COLUMN IF NOT EXISTS level_nm     text;
CREATE INDEX IF NOT EXISTS user_recipe_user_created_idx ON recipebook.user_recipe (user_id, created_at DESC);

-- 발행(공개 카탈로그) — 유저가 자기 user_recipe를 "레시피 목록"에 공개 발행하면 이 테이블에 스냅샷.
-- 검색은 이 표를 카탈로그(public.recipe)와 프론트에서 합쳐 노출. 원본 FK는 같은 스키마 → 진짜 FK.
-- 원본 삭제/비공개 시 CASCADE·별도 삭제로 목록에서 사라진다. user_recipe_id UNIQUE → 재발행=업서트.
CREATE TABLE IF NOT EXISTS recipebook.shared_recipe (
  id             bigserial PRIMARY KEY,
  user_recipe_id bigint NOT NULL UNIQUE REFERENCES recipebook.user_recipe(id) ON DELETE CASCADE,
  user_id        bigint NOT NULL,                                    -- 발행자(논리값)
  title          text NOT NULL,
  image_url      text,
  ingredients    jsonb,
  steps          jsonb,
  source_url     text,
  origin         text NOT NULL,                                      -- 원본에서 복사(MANUAL/YOUTUBE)
  share_token    text NOT NULL UNIQUE,                               -- 공개 뷰(/shared/:token) 재사용
  published_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS shared_recipe_published_idx ON recipebook.shared_recipe (published_at DESC);

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
-- 기본 목록(unread 미지정) 경로: WHERE user_id ORDER BY created_at DESC — is_read가 중간 컬럼인 위 인덱스로는
-- 정렬을 못 타 sort가 발생. 이 인덱스가 기본 경로 정렬을 커버(부하테스트 후속, #186).
CREATE INDEX IF NOT EXISTS notification_user_created_idx ON notify.notification (user_id, created_at DESC);
-- 최저가 재알림 쿨다운(7일) 조회 전용. fan-out 컨슈머가 매 이벤트마다 "이 유저에게 이 품목을 최근에
-- 보냈나"를 확인하는데, payload->>'item_id' 는 일반 인덱스로 못 타 알림이 쌓일수록 순차 스캔이 된다.
-- LOW_PRICE 만 대상인 부분 인덱스라 크기도 작다(#9, ai-spec §2).
CREATE INDEX IF NOT EXISTS notification_lowprice_cooldown_idx
  ON notify.notification (user_id, ((payload->>'item_id')), created_at DESC)
  WHERE type = 'LOW_PRICE';

CREATE TABLE IF NOT EXISTS notify.notification_setting (
  user_id    bigint PRIMARY KEY,
  low_price  boolean NOT NULL DEFAULT true,
  expiry     boolean NOT NULL DEFAULT true,
  hotdeal    boolean NOT NULL DEFAULT true,
  budget     boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- ==================== chat (Chatbot 대화 로그) ====================
-- 챗봇 대화 저장 — 멀티턴·개인화·AI 리포트 재료(docs/chat-conversation-data-plan.md §2·§8 D-1).
-- ⚠️ 동의 게이팅(D-2): 미동의 유저 대화는 앱 write 시점에 저장 안 함(무상태). 이 테이블은 동의 유저만.
-- 보존(D-3): 원문 단기(90~180일 협의) → 이후 집계·익명화. user_id·item_ids=크로스서비스 논리값(FK X).
CREATE TABLE IF NOT EXISTS chat.chat_message (
  id          bigserial PRIMARY KEY,
  user_id     bigint,                                        -- 논리값(account.app_user) · 동의 유저만
  session_id  uuid NOT NULL,                                 -- 멀티턴 묶음
  role        text NOT NULL CHECK (role IN ('user','bot')),
  text        text NOT NULL,                                 -- 발화 내용
  intent      text,                                          -- recommend/price/nutrition/unknown
  item_ids    bigint[],                                      -- 추출 표준품목(논리값)
  unanswered  boolean,                                       -- bot 미응답 여부(품질 분석)
  basis       jsonb,                                         -- 근거 태그(레시피·가격·영양)
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chat_message_session_created_idx ON chat.chat_message (session_id, created_at);
CREATE INDEX IF NOT EXISTS chat_message_created_idx ON chat.chat_message (created_at);

-- ==================== activity (클릭스트림 — 개인화 랭킹 피처) ====================
-- 유저 행동 이벤트 + 노출 로그 — P1 레시피 랭킹(LightGBM) 학습·서빙 재료(docs/user-behavior-data-request.md §2·§3).
-- ⚠️ 동의 게이팅(§4): 미동의 유저 이벤트는 앱/컨슈머가 produce 안 함. append-only(정정=새 이벤트, UPDATE/DELETE 금지).
-- 참조 전부 논리값(FK X): 이벤트 로그를 카탈로그 lifecycle과 분리(레시피/품목 삭제돼도 이력 보존)·write 성능. 삭제권=앱 처리.
-- event_id/impression_id = producer 발급 멱등키 → 컨슈머 at-least-once 재전달 dedup(ON CONFLICT DO NOTHING).
CREATE TABLE IF NOT EXISTS activity.user_event (
  id          bigserial PRIMARY KEY,
  event_id    uuid NOT NULL UNIQUE,                           -- producer 발급 멱등키(재전달 dedup)
  user_id     bigint NOT NULL,                                -- 논리값(account.app_user) · 동의 유저만
  session_id  uuid,
  event_type  text NOT NULL CHECK (event_type IN ('VIEW','ADD_CART','NOTIF_CLICK')),
  recipe_id   bigint,                                         -- 논리값(public.recipe)
  item_id     bigint,                                         -- 논리값(public.item_master) · NOTIF_CLICK 임박품목 등
  occurred_at timestamptz NOT NULL,                           -- 클라 발생시각(UTC), 서버수신 아님
  context     jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS user_event_user_occurred_idx ON activity.user_event (user_id, occurred_at);
CREATE INDEX IF NOT EXISTS user_event_recipe_type_idx   ON activity.user_event (recipe_id, event_type);
CREATE INDEX IF NOT EXISTS user_event_type_occurred_idx ON activity.user_event (event_type, occurred_at);

-- 노출 로그 — 랭커가 보여준 레시피 + 순위 + 규칙점수(부정 라벨). AI 랭커(mealplan)가 emit(제품기능 무관).
CREATE TABLE IF NOT EXISTS activity.recipe_impression (
  id            bigserial PRIMARY KEY,
  impression_id uuid NOT NULL UNIQUE,                         -- 랭커 발급 멱등키(재전달 dedup)
  user_id       bigint NOT NULL,                              -- 논리값
  session_id    uuid,
  shown_at      timestamptz NOT NULL,
  recipe_id     bigint NOT NULL,                              -- 논리값(public.recipe)
  rank          int NOT NULL,                                 -- 노출 순위(1=최상단)
  rule_score    numeric,
  score_stock   numeric,
  score_expiry  numeric,
  score_cost    numeric,                                      -- P1 피처(규칙점수 분해 3종)
  request_ctx   jsonb                                         -- 예산잔여·의도(F11/F16)·재고스냅샷 요약
);
CREATE INDEX IF NOT EXISTS recipe_impression_user_shown_idx ON activity.recipe_impression (user_id, shown_at);
CREATE INDEX IF NOT EXISTS recipe_impression_recipe_idx     ON activity.recipe_impression (recipe_id);

-- 인기도 누적 집계 — 보존배치(prune_user_data)가 원문(user_event) 삭제 前 ADD_CART/VIEW 카운트를 여기로 승격(§4.1).
-- ⚠️ 서빙 인기도 = 이 테이블(삭제분 누적) + 보존창 내 원문 카운트 합산. 원문이 retention 만료로 삭제돼도 유실 없음.
-- 누적 upsert와 원문 DELETE는 프루너에서 한 트랜잭션 → 각 행 정확히 1회 집계(멱등).
CREATE TABLE IF NOT EXISTS activity.recipe_popularity (
  recipe_id    bigint PRIMARY KEY,                 -- 논리값(public.recipe) · upsert 대상
  add_cart_cnt bigint NOT NULL DEFAULT 0,          -- 삭제 승격된 ADD_CART 누적(주 긍정 라벨)
  view_cnt     bigint NOT NULL DEFAULT 0,          -- 삭제 승격된 VIEW 누적(약 긍정)
  updated_at   timestamptz NOT NULL DEFAULT now()  -- 마지막 승격 시각
);

-- 대화 유래 개인화 신호 — 챗 로그(chat.chat_message) 분석(ml/chat-insights preferences.py)이 upsert.
--   랭킹이 user_ing_affinity 피처를 이 선호로 보강(design.md §4.1 대화 분석 · chat-conversation-data-plan §1.2).
CREATE TABLE IF NOT EXISTS activity.user_chat_pref (
  user_id            bigint PRIMARY KEY,              -- 논리값(account.app_user) · 동의 유저
  liked_item_ids     bigint[] NOT NULL DEFAULT '{}',  -- 자주 언급 표준품목(선호) → 랭킹 user_ing_affinity 보강
  disliked_item_ids  bigint[] NOT NULL DEFAULT '{}',  -- 제외 맥락 언급(비선호) — 추천 회피
  budget_sensitivity real NOT NULL DEFAULT 0,         -- 가격 민감도(0~1, price/recipe_cost 의도 비율)
  updated_at         timestamptz NOT NULL DEFAULT now()
);
