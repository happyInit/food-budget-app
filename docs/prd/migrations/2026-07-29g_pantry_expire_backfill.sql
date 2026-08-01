-- 재고 소비기한 소급 계산 (A안 — CURATED 출처만).
--
-- ── 왜 필요한가 ─────────────────────────────────────────────────────────────
-- `pantry_item.expire_at` 은 **등록 시점에 한 번만** 계산된다(`routers.py`: 등록 시
-- `lookup_shelf_life` → `estimate_expire_date`). 그때 참조표에 값이 없으면 NULL 로 저장되고,
-- **나중에 참조표를 채워도 자동으로 재계산되지 않는다.**
--
-- 2026-07-29 에 상비 큐레이션(29c/d/e/f)과 AI 초안을 넣기 **전**(07-16~07-22)에 등록된 재고가
-- 그 상태다 — 지금 조회하면 값이 나오는데 컬럼은 비어 있어 **임박 알림에 영영 안 잡힌다.**
--
-- ── 왜 CURATED 만 하는가 (A안) ──────────────────────────────────────────────
-- 대상 17건을 출처로 나누면 정확히 갈린다:
--   · CURATED 12건  → 전부 **미래 날짜**(+51 ~ +723일). 상비·냉동이라 기한이 길다.
--   · AI_DRAFT  5건 → 전부 **이미 지난 날짜**(−6 ~ −10일). 신선식품이라 1~5일이고
--                     7~13일 전 등록분이라 당연히 지났다(곤드레나물·샤인머스캣·삼치·얼갈이).
--
-- AI_DRAFT 를 함께 넣으면 유저 화면에 5건이 즉시 "만료됨"으로 뜬다. 정보로는 정확할 수 있으나
-- **미검수 AI 추정값을 근거로 "버려라"라고 말하는 셈**이다(검증 백로그 §1.2 미검수 상태).
-- → CURATED 12건만 소급한다. 전부 미래 날짜라 **유저에게 갑작스러운 만료 표시가 0건**이고,
--    가장 가까운 것도 마요네즈 +51일이라 임박 알림(7일)에도 걸리지 않는다.
--    AI_DRAFT 분은 검수 후 별도로 판단한다.
--
-- ── 계산식 ──────────────────────────────────────────────────────────────────
-- 등록 시점 로직과 **동일**하다: `estimate_expire_date(added, days_min, days_max)`
--   = added + (days_max ?? days_min).  여기서 added = `created_at::date`.
-- days_max 가 NULL 인 행(기한 추정 대상 아님 — 소금·설탕 등)은 대상이 아니다.
--
-- 적용:
--   psql -h 192.168.0.8 -U fbapp -d foodbudget -v ON_ERROR_STOP=1 \
--        -f docs/prd/migrations/2026-07-29g_pantry_expire_backfill.sql

BEGIN;

-- 되돌릴 수 있도록 변경 전 상태를 남긴다(같은 트랜잭션 안에서 생성 → 실패 시 함께 롤백).
CREATE TABLE IF NOT EXISTS pantry.pantry_expire_backfill_log (
  pantry_item_id bigint PRIMARY KEY,
  new_expire_at  date        NOT NULL,
  source         text        NOT NULL,
  applied_at     timestamptz NOT NULL DEFAULT now()
);

WITH target AS (
  SELECT p.id,
         p.created_at::date AS added,
         (SELECT s.days_max
            FROM public.shelf_life_ref s
           WHERE s.item_id = p.item_id
             AND s.storage = p.storage
             AND s.source  = 'CURATED'        -- ⚠️ A안: 사람 검수본만
             AND s.days_max IS NOT NULL
           ORDER BY s.days_max                -- 여러 개면 **가장 짧은 쪽**(보수적)
           LIMIT 1) AS days_max
    FROM pantry.pantry_item p
   WHERE p.expire_at IS NULL
     AND p.item_id IS NOT NULL
), calc AS (
  SELECT id, (added + days_max) AS new_expire FROM target WHERE days_max IS NOT NULL
), logged AS (
  INSERT INTO pantry.pantry_expire_backfill_log (pantry_item_id, new_expire_at, source)
  SELECT id, new_expire, 'CURATED' FROM calc
  ON CONFLICT (pantry_item_id) DO NOTHING
  RETURNING pantry_item_id
)
UPDATE pantry.pantry_item p
   SET expire_at = c.new_expire
  FROM calc c
 WHERE p.id = c.id AND p.expire_at IS NULL;   -- 재실행 안전: 이미 채워진 행은 건드리지 않는다

COMMIT;

-- 적용 확인:
--   select count(*) from pantry.pantry_expire_backfill_log;                    -- 12
--   select count(*) from pantry.pantry_item where expire_at is null;           -- 49 → 37
--   -- 임박(7일) 대상이 늘지 않았는지 — A안의 핵심 전제
--   select count(*) from pantry.pantry_item
--    where status='ACTIVE' and expire_at is not null and expire_at <= current_date + 7;
--
-- 롤백:
--   UPDATE pantry.pantry_item p SET expire_at = NULL
--     FROM pantry.pantry_expire_backfill_log l
--    WHERE p.id = l.pantry_item_id AND p.expire_at = l.new_expire_at;
--   DELETE FROM pantry.pantry_expire_backfill_log;
