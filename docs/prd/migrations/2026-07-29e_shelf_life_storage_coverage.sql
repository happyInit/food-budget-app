-- 보관구역 커버리지 보정 (2026-07-29c/d 후속) — 조회는 (item_id, storage) 조합으로 한다.
--
-- ── 무엇을 놓쳤나 ───────────────────────────────────────────────────────────
-- `lookup_shelf_life(item_id, storage)` 는 **조합**으로 찾는데, 앞선 시드는 상비를 대부분
-- ROOM 에만 넣었다. 그런데 실측(2026-07-29) 유저 재고는 다르게 보관한다:
--     소금 FRIDGE 4 · FREEZER 2 · 설탕 FRIDGE 2 · FREEZER 1 · 후추 FRIDGE 2 · 통깨 FREEZER 1 …
-- 그래서 item_id 는 커버됐는데 **조합이 안 맞아 조회가 계속 None** 이었다.
-- (앞선 검증이 item_id 만 보고 "29 → 6건"으로 잘못 보고했다. 조합 기준으로는 29건 그대로였다.)
--
-- 두 번째 구멍: **FREEZER 를 AI 초안 대상에서 제외**했더니(모델이 일괄 6~12일을 내는 퇴화 출력)
-- 냉동 보관 품목이 통째로 비었다 — 깻잎·계란·새송이버섯 FREEZER 등.
--
-- ── 처방 ────────────────────────────────────────────────────────────────────
-- ① **기한 추정 대상 아님 9종** → ROOM/FRIDGE/FREEZER **전 보관**에 days NULL 행.
--    소금은 냉장고에 넣어도 상하지 않는다. 보관구역과 무관한 속성이다.
-- ② **신선식품 FREEZER** → **분류별 표준 냉동 보존기간**을 규칙으로 넣는다(CURATED).
--    AI 추정이 아니라 통용되는 식품보존 가이드 값이라 근거가 있고 재현 가능하다.
--    냉동은 미생물 증식이 멈춰 안전기한보다 **품질 저하**가 기준이므로 넉넉하게 잡되,
--    무제한은 아니다(냉동상해·산패).
--
-- 적용:
--   psql -h 192.168.0.8 -U fbapp -d foodbudget -v ON_ERROR_STOP=1 \
--        -f docs/prd/migrations/2026-07-29e_shelf_life_storage_coverage.sql

BEGIN;

-- ── ① 기한 추정 대상 아님 — 전 보관구역으로 확장 ────────────────────────────
INSERT INTO public.shelf_life_ref (source, food_category, item_name, storage,
                                   days_min, days_max, note, item_id)
SELECT 'CURATED', r.food_category, r.item_name, st.storage, NULL, NULL,
       '기한 추정 대상 아님 — 포장의 품질유지기한 표기를 따른다', r.item_id
  FROM public.shelf_life_ref r
 CROSS JOIN (VALUES ('ROOM'), ('FRIDGE'), ('FREEZER')) AS st(storage)
 WHERE r.source = 'CURATED' AND r.days_min IS NULL AND r.days_max IS NULL
   AND NOT EXISTS (
     SELECT 1 FROM public.shelf_life_ref x
      WHERE x.item_id = r.item_id AND x.storage = st.storage
   );

-- ── ② 신선식품 냉동 — 분류별 표준 보존기간 ──────────────────────────────────
-- 값 근거: 통용 식품보존 가이드(냉동 −18℃ 기준). 안전보다 **품질 저하**가 기준이라
-- 냉장보다 훨씬 길다. 냉동상해·산패로 무제한은 아니다.
INSERT INTO public.shelf_life_ref (source, food_category, item_name, storage,
                                   days_min, days_max, note, item_id)
SELECT 'CURATED', im.category, im.canonical_name, 'FREEZER', v.dmin, v.dmax,
       '냉동 표준 보존기간(분류 규칙) — 품질 기준', im.item_id
  FROM item_master im
  JOIN (VALUES
        ('육류',   90, 180),
        ('수산물', 60, 180),
        ('채소',  180, 365),
        ('과일',  180, 365),
        ('버섯',  180, 270),
        ('유제품', 30,  90)
       ) AS v(cat, dmin, dmax) ON v.cat = im.category
 WHERE NOT EXISTS (
   SELECT 1 FROM public.shelf_life_ref x
    WHERE x.item_id = im.item_id AND x.storage = 'FREEZER'
 )
 -- 건조품은 냉동 대상이 아니다(상온 장기) — 2026-07-29 초안에서 걸러낸 것과 같은 기준.
 AND im.canonical_name !~ '건조|말린|황태|북어|건포도|건새우|말랭이|가루|분말|차$';

COMMIT;

-- 적용 확인:
--   -- 조합(item_id, storage) 기준 재고 커버리지 — 이게 lookup_shelf_life 와 같은 조건이다
--   select count(*) filter (where p.item_id is not null and exists (
--            select 1 from public.shelf_life_ref s
--             where s.item_id=p.item_id and s.storage=p.storage)) as combo_hit,
--          count(*) filter (where p.item_id is not null and not exists (
--            select 1 from public.shelf_life_ref s
--             where s.item_id=p.item_id and s.storage=p.storage)) as combo_miss
--     from pantry.pantry_item p where p.expire_at is null;
--
-- 롤백:
--   delete from public.shelf_life_ref
--    where source='CURATED' and note = '냉동 표준 보존기간(분류 규칙) — 품질 기준';
--   -- ①은 note 가 기존과 같아 fetched_at 기준으로 이번 배치분만 지울 것.
