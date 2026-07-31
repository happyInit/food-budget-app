-- 🔴 프리플라이트 — DDL 적용 **전에** 반드시 먼저 실행한다.
--
-- 이 설계는 작업 PC 가 DB 에 닿지 않는 상태에서 **스키마 파일만 보고** 만들어졌다.
-- 실 DB 가 스키마 파일과 다를 수 있으므로(수동 변경·마이그레이션 누락·다른 DB 접속),
-- 전제가 실제로 성립하는지 먼저 검사한다. 하나라도 어긋나면 EXCEPTION 으로 중단된다.
--
-- 읽기 전용이다 — 어떤 것도 생성·변경하지 않는다.
--
-- 실행:
--   psql -h 192.168.0.8 -U fbapp -d foodbudget -f docs/prd/migrations/2026-07-29_preflight.sql
--
-- 통과 = 마지막 줄에 "PREFLIGHT PASS" 출력 + 종료코드 0
-- 실패 = EXCEPTION 으로 중단(종료코드 3). 메시지가 어긋난 전제를 지목한다.

\set ON_ERROR_STOP on

DO $$
DECLARE
  fails text[] := '{}';
  warns text[] := '{}';
  n     bigint;   -- 카운트 결과
  i     int;      -- 메시지 출력 루프
BEGIN
  RAISE NOTICE '';
  RAISE NOTICE '=== 프리플라이트: 설계 전제 검증 (읽기 전용) ===';
  RAISE NOTICE '접속 DB=% / 사용자=%', current_database(), current_user;
  RAISE NOTICE '';

  -- ── A. 리뷰 트랙 전제 ──────────────────────────────────────────────────────
  -- A1. recipe 테이블 + 크롤러가 SELECT 하는 컬럼 3개
  IF to_regclass('public.recipe') IS NULL THEN
    fails := fails || 'A1 recipe 테이블이 없다 — 다른 DB 에 접속했을 가능성'::text;
  ELSE
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='recipe' AND column_name='id') THEN
      fails := fails || 'A1 recipe.id 없음 (FK 대상)'::text;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='recipe' AND column_name='source') THEN
      fails := fails || 'A1 recipe.source 없음 (크롤 대상 필터)'::text;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='recipe' AND column_name='src_recipe_id') THEN
      fails := fails || 'A1 recipe.src_recipe_id 없음 (만개 ID)'::text;
    END IF;
  END IF;

  -- A2. 크롤 대상이 실제로 있는가 — 0건이면 크롤러가 아무것도 안 한다
  IF to_regclass('public.recipe') IS NOT NULL THEN
    EXECUTE 'select count(*) from recipe where source = ''10K'' and src_recipe_id is not null'
      INTO n;
    RAISE NOTICE 'A2 크롤 대상(source=10K): % 건', n;
    IF n = 0 THEN
      fails := fails || 'A2 source=10K 레시피가 0건 — 크롤러가 대상을 못 찾는다'::text;
    ELSIF n < 100 THEN
      warns := warns || format('A2 대상이 %s 건뿐 — 만개 크롤이 아직 덜 돌았을 수 있다', n);
    END IF;
  END IF;

  -- ── B. 가격 트랙 전제 ──────────────────────────────────────────────────────
  -- B1. FK 대상
  IF to_regclass('public.item_master') IS NULL THEN
    fails := fails || 'B1 item_master 없음 (price_baseline/price_anomaly FK 대상)'::text;
  END IF;

  -- B2. 기준선 계산 입력 — retail_price(시계열) × retail_product(weight_g)
  --     ⚠️ retail_unit_price(뷰)는 rn=1 최신만이라 이동평균 입력이 못 된다. 여기서 원천을 본다.
  IF to_regclass('public.retail_price') IS NULL THEN
    fails := fails || 'B2 retail_price 없음 (30일 이동평균의 시계열 원천)'::text;
  ELSE
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='retail_price' AND column_name='crawled_at') THEN
      fails := fails || 'B2 retail_price.crawled_at 없음 (윈도우 기준)'::text;
    END IF;
  END IF;

  IF to_regclass('public.retail_product') IS NULL THEN
    fails := fails || 'B2 retail_product 없음'::text;
  ELSE
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='retail_product' AND column_name='weight_g') THEN
      fails := fails || 'B2 retail_product.weight_g 없음 (won_per_100g 정규화 불가)'::text;
    END IF;
  END IF;

  -- B3. 시계열이 실제로 30일치 쌓였는가 — ai-spec §4.1 "4주 미만 오탐↑"
  -- 주의: **KST 영업일**로 센다. DB 세션 TZ 가 UTC 라 crawled_at::date 로 끊으면 한 UTC 날짜에
  -- 서로 다른 KST 날짜가 섞여 일수가 실제와 어긋난다(컬리 03:30 KST = 18:30 UTC 전날).
  IF to_regclass('public.retail_price') IS NOT NULL THEN
    EXECUTE 'select count(distinct (crawled_at at time zone ''Asia/Seoul'')::date) from retail_price
              where crawled_at > now() - interval ''30 days'''
      INTO n;
    RAISE NOTICE 'B3 최근 30일 중 크롤된 일수: % 일', n;
    IF n = 0 THEN
      fails := fails || 'B3 최근 30일 가격 이력이 0건 — 기준선을 만들 수 없다'::text;
    ELSIF n < 28 THEN
      warns := warns || format('B3 관측 %s일 < 28일 — 기준선이 미성숙, 오탐 구간이다(탐지 게이트 필요)', n);
    END IF;
  END IF;

  -- ── C. 알림 도메인 전제 (재사용 — 신규 생성하지 않음) ──────────────────────
  IF to_regclass('price.price_watch') IS NULL THEN
    fails := fails || 'C1 price.price_watch 없음 (팬아웃 대상 = 관심 등록 유저)'::text;
  END IF;

  IF to_regclass('notify.notification') IS NULL THEN
    fails := fails || 'C2 notify.notification 없음 (알림 본문 착지점)'::text;
  ELSE
    -- type CHECK 에 LOW_PRICE 가 실제로 허용되는지 — 없으면 알림 insert 가 런타임에 실패한다
    IF NOT EXISTS (
      SELECT 1 FROM pg_constraint c
       WHERE c.conrelid = 'notify.notification'::regclass
         AND c.contype = 'c'
         AND pg_get_constraintdef(c.oid) LIKE '%LOW_PRICE%'
    ) THEN
      fails := fails || 'C2 notify.notification.type CHECK 에 LOW_PRICE 가 없다 — 알림 insert 가 실패한다'::text;
    END IF;
  END IF;

  -- ── D. 신규 테이블 충돌 검사 ──────────────────────────────────────────────
  -- 이미 있으면 마이그레이션은 IF NOT EXISTS 로 건너뛴다. 문제는 **모양이 다를 때**다.
  IF to_regclass('public.recipe_review') IS NOT NULL THEN
    warns := warns || 'D1 recipe_review 가 이미 존재 — 마이그레이션은 건너뛴다. 컬럼 일치를 수동 확인할 것'::text;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name='recipe_review' AND column_name='nickname') THEN
      fails := fails || 'D1 기존 recipe_review 에 nickname 컬럼이 있다 — 이번 설계(닉네임 미저장)와 불일치'::text;
    END IF;
  END IF;

  IF to_regclass('public.price_anomaly') IS NOT NULL THEN
    warns := warns || 'D2 price_anomaly 가 이미 존재 — 컬럼 일치를 수동 확인할 것'::text;
  END IF;

  -- ── 판정 ──────────────────────────────────────────────────────────────────
  RAISE NOTICE '';
  IF array_length(warns, 1) IS NOT NULL THEN
    RAISE NOTICE '--- 경고 (진행 가능, 인지 필요) ---';
    FOREACH i IN ARRAY ARRAY(SELECT generate_series(1, array_length(warns, 1))) LOOP
      RAISE NOTICE '  ⚠️  %', warns[i];
    END LOOP;
    RAISE NOTICE '';
  END IF;

  IF array_length(fails, 1) IS NOT NULL THEN
    RAISE NOTICE '--- 실패 (진행 금지) ---';
    FOREACH i IN ARRAY ARRAY(SELECT generate_series(1, array_length(fails, 1))) LOOP
      RAISE NOTICE '  ❌ %', fails[i];
    END LOOP;
    RAISE EXCEPTION E'\n\nPREFLIGHT FAIL — 전제 % 건이 어긋났다. DDL 을 적용하지 말 것.\n'
                    '설계는 스키마 파일 기준으로 만들어졌으므로, 실 DB 가 다르면 설계를 먼저 고쳐야 한다.',
                    array_length(fails, 1);
  END IF;

  RAISE NOTICE 'PREFLIGHT PASS — 전제가 모두 성립한다. DDL 을 적용해도 된다.';
  RAISE NOTICE '';
END $$;
