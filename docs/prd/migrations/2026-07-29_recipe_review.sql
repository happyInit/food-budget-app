-- 리뷰 수집·분석 테이블 신설 (schema-public-data.sql §G 와 동일 내용의 적용용 스크립트).
--
-- 전체 스키마 파일은 기존 테이블에서 `already exists` 로 죽으므로, 신규분만 담은 이 파일로 적용한다.
-- 전부 IF NOT EXISTS 라 여러 번 돌려도 안전.
--
-- 적용:
--   psql -h 192.168.0.8 -U fbapp -d foodbudget -f docs/prd/migrations/2026-07-29_recipe_review.sql
--
-- 선행조건: recipe 테이블 존재(FK 대상). 없으면 즉시 실패한다 — 잘못된 DB 를 가리킨 것이다.
-- 롤백: 파일 하단 주석 참조.

BEGIN;

-- 원문. 닉네임은 저장하지 않는다 — 감정분류·요약 어디에도 쓰이지 않는 개인정보.
CREATE TABLE IF NOT EXISTS recipe_review (
  id         bigserial PRIMARY KEY,
  recipe_id  bigint NOT NULL REFERENCES recipe(id) ON DELETE CASCADE,
  seq        int    NOT NULL,          -- 페이지 노출 순번(1-base)
  body       text   NOT NULL,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (recipe_id, seq)              -- 재크롤 멱등(ON CONFLICT DO UPDATE)
);
CREATE INDEX IF NOT EXISTS recipe_review_recipe_id_idx ON recipe_review (recipe_id);

-- 크롤 시도 결과 — 리뷰 0건·실패도 남겨 재실행 시 반복 요청을 막는다.
CREATE TABLE IF NOT EXISTS recipe_review_crawl (
  recipe_id    bigint PRIMARY KEY REFERENCES recipe(id) ON DELETE CASCADE,
  status       text NOT NULL CHECK (status IN ('ok','no_review','fail')),
  reason       text,                   -- status='fail' 일 때만
  review_count int  NOT NULL DEFAULT 0,
  attempted_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS recipe_review_crawl_fail_idx
  ON recipe_review_crawl (status) WHERE status = 'fail';

-- 파생 ① 건당 감정 라벨. model 이 재실행 판단 근거 — 모델 교체 시 대상 행을 쿼리로 특정.
CREATE TABLE IF NOT EXISTS recipe_review_sentiment (
  review_id bigint PRIMARY KEY REFERENCES recipe_review(id) ON DELETE CASCADE,
  label     text NOT NULL CHECK (label IN ('positive','negative','neutral')),
  model     text NOT NULL,             -- 예 apac.amazon.nova-micro-v1:0
  scored_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS recipe_review_sentiment_label_idx
  ON recipe_review_sentiment (label);

-- 파생 ② 레시피당 집계 + AI 요약(표시용).
CREATE TABLE IF NOT EXISTS recipe_review_summary (
  recipe_id     bigint PRIMARY KEY REFERENCES recipe(id) ON DELETE CASCADE,
  review_count  int     NOT NULL,
  positive_rate numeric NOT NULL,      -- 0~100
  summary       text,                  -- 2~3문장. 모델 미확정이라 NULL 허용
  model         text,
  generated_at  timestamptz NOT NULL DEFAULT now()
);

COMMIT;

-- 적용 확인:
--   \d recipe_review
--   select count(*) from recipe where source = '10K';   -- 크롤 대상 건수
--
-- 롤백(신규분만 제거 — 기존 recipe 는 건드리지 않음):
--   DROP TABLE IF EXISTS recipe_review_summary, recipe_review_sentiment,
--                        recipe_review_crawl, recipe_review CASCADE;
