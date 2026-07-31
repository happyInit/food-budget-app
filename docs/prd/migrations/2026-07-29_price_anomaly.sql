-- 가격 이상치 탐지(#9) + 관심재료 최저가 알림(#6) — 신규 테이블 3개.
--
-- 근거: ai-spec.md §2(z-score·30일 이동평균·컬리/오아시스 2축) · ai-features-roadmap §6·§9 ·
--       실 DB 검증 2026-07-24(매칭 kurly 87.3%/oasis 91.7% · overlap 237개).
--
-- 재사용하는 기존 자산 (신규 생성하지 않는다):
--   · price.price_watch          — 관심 등록(user_id, item_id). ai-spec §2 "ⓐ 명시 등록" 확정분.
--   · notify.notification        — 발송 이력. type='LOW_PRICE' 가 이미 CHECK 에 있다.
--   · notify.notification_setting— 유저별 low_price 수신 여부.
--   · retail_price + retail_product — 시계열 원천(크롤 스냅샷).
--
-- ⚠️ retail_unit_price(물질화 뷰)는 rn=1 최신 스냅샷만이라 이동평균의 입력이 될 수 없다.
--    기준선은 retail_price(시계열) × retail_product(weight_g) 로 직접 계산한다.
--
-- 적용:
--   psql -h 192.168.0.8 -U fbapp -d foodbudget -f docs/prd/migrations/2026-07-29_price_anomaly.sql

BEGIN;

-- ── ① 품목별 가격 기준선 (배치 산출물) ────────────────────────────────────────
-- ai-spec §2 "① 품목별 평상시 가격 기준선". 매 탐지마다 30일 윈도우를 재계산하지 않기 위한
-- 스냅샷이자, **알림의 근거를 재현하기 위한 기록**이다 — "왜 3,990원이 이상인가"에
-- μ·σ·표본수로 답할 수 있어야 챗봇의 근거 태그(§RAG)와 사후 오탐 분석이 가능하다.
--
-- 단위는 won_per_100g 로 정규화한다. 컬리·오아시스는 팩 크기가 달라 raw price 를 그대로
-- 섞으면 σ 가 팩 크기 아티팩트로 부풀고, 진짜 급락이 묻힌다. 100g 단가로 정규화해야
-- ai-spec 이 말하는 "2축이라 baseline 이 2배 속도로 축적"이 성립한다(같은 축에 쌓임).
--
-- ⚠️ obs_count 가 게이트다. ai-spec §4.1 "baseline 4주 미만 구간은 오탐↑" 을 코드가 아니라
--    데이터로 판정하기 위해 표본수를 남긴다 — 임계 미만이면 탐지를 건너뛴다.
CREATE TABLE IF NOT EXISTS price_baseline (
  item_id     bigint  NOT NULL REFERENCES item_master(item_id) ON DELETE CASCADE,
  as_of       date    NOT NULL,            -- 산출 기준일(배치 실행일)
  window_days int     NOT NULL DEFAULT 30, -- 이동평균 창(ai-spec §2 = 30일)
  mean_100g   numeric NOT NULL,            -- μ — won_per_100g 평균
  stddev_100g numeric NOT NULL,            -- σ — 품목별 변동성. "원래 출렁이는 품목" 구분의 핵심
  min_100g    numeric,                     -- 창 내 최저 — 역대최저 갱신 판정 보조신호
  obs_count   int     NOT NULL,            -- 표본수. 4주 미만 오탐 게이트
  computed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (item_id, as_of)             -- 일자별 1행 → 재실행 멱등
);
CREATE INDEX IF NOT EXISTS price_baseline_asof_idx ON price_baseline (as_of DESC);

-- ── ② 이상 급락 이벤트 ────────────────────────────────────────────────────────
-- ai-spec §2 "③ 급락 판정(z ≤ −2.0) → ⑤ Kafka events.price.anomaly 발행".
-- 이 테이블은 발행 전 착지점이자 팬아웃의 소스다. 이벤트를 남기는 이유 셋:
--   1. 중복 발행 방지 — 같은 품목의 같은 급락을 하루에 여러 번 알리지 않는다.
--   2. 오탐률 측정 — ai-spec 이 경고한 초기 오탐 구간을 사후에 수치로 확인해야 임계를 조정한다.
--   3. 알림 근거 — 유저에게 "평소 5,200원인데 오늘 3,990원(z=-3.0)" 을 보여주려면 값이 남아야 한다.
--
-- retail_price_id 로 **실제 상품 스냅샷**을 가리킨다 — ai-features-roadmap §6 "합성금액 금지,
-- 화면엔 실상품+실가격+용량+시점" 원칙을 스키마 수준에서 강제한다.
CREATE TABLE IF NOT EXISTS price_anomaly (
  id                bigserial PRIMARY KEY,
  item_id           bigint NOT NULL REFERENCES item_master(item_id) ON DELETE CASCADE,
  detected_on       date   NOT NULL,       -- 탐지 기준일
  source            text   NOT NULL CHECK (source IN ('kurly','oasis')),
  retail_product_id bigint NOT NULL REFERENCES retail_product(id) ON DELETE CASCADE,
  crawled_at        timestamptz NOT NULL,  -- 근거가 된 스냅샷 시점(retail_price PK 일부)
  price             numeric NOT NULL,      -- 실제 판매가(표시용 — 합성 아님)
  price_100g        numeric NOT NULL,      -- 판정에 쓴 정규화 단가
  z_score           numeric NOT NULL,      -- (price_100g − μ) / σ
  baseline_mean     numeric NOT NULL,      -- 판정 시점의 μ 사본 — 나중에 baseline 이 바뀌어도 근거 보존
  baseline_stddev   numeric NOT NULL,
  is_record_low     boolean NOT NULL DEFAULT false,  -- 보조신호: 역대 최저 갱신
  discount_rate     int,                             -- 보조신호: 정가 대비 할인율
  published_at      timestamptz,           -- Kafka events.price.anomaly 발행 시각. NULL=미발행
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (item_id, detected_on, source)    -- 품목·일자·소스당 1건 → 배치 재실행 멱등
);
CREATE INDEX IF NOT EXISTS price_anomaly_unpublished_idx
  ON price_anomaly (created_at) WHERE published_at IS NULL;   -- 미발행 스캔

-- ── ③ 팬아웃 발송 이력 ────────────────────────────────────────────────────────
-- ai-spec §2 "이상탐지 컨슈머 → 관심 등록 유저 fan-out (KEDA)". KEDA 로 스케일되는 Kafka
-- 컨슈머는 at-least-once 라 **같은 이벤트를 두 번 처리할 수 있다**. UNIQUE 가 중복 발송의
-- 유일한 방어선이다 — 알림 피로도는 ai-spec 이 "관건" 이라 명시한 항목이다.
--
-- 알림 본문 자체는 notify.notification 에 들어간다(type='LOW_PRICE', 이미 존재).
-- 이 테이블은 그 연결·멱등만 담당한다 — 알림 도메인을 침범하지 않는다.
CREATE TABLE IF NOT EXISTS price_alert_sent (
  anomaly_id      bigint NOT NULL REFERENCES price_anomaly(id) ON DELETE CASCADE,
  user_id         bigint NOT NULL,
  notification_id bigint,              -- notify.notification.id (스키마 분리라 FK 없이 참조)
  sent_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (anomaly_id, user_id)    -- 재처리해도 1회만
);
CREATE INDEX IF NOT EXISTS price_alert_sent_user_idx ON price_alert_sent (user_id, sent_at DESC);

COMMIT;

-- 적용 확인:
--   \d price_baseline
--   select count(*) from price.price_watch;            -- 관심 등록 건수(팬아웃 대상)
--   select count(distinct rp.item_id) from retail_product rp where rp.item_id is not null;
--
-- 롤백:
--   DROP TABLE IF EXISTS price_alert_sent, price_anomaly, price_baseline CASCADE;
