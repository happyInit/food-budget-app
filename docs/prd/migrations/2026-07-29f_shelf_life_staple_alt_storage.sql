-- 상비품 비표준 보관 보정 (2026-07-29e 후속).
--
-- ── 무엇을 놓쳤나 ───────────────────────────────────────────────────────────
-- 상비 시드는 표준 보관(대개 ROOM)만 넣었는데, 실측 유저 재고는 다르게 보관한다:
--     식용유 FRIDGE · 박력분 FRIDGE · 통깨 FREEZER
-- `lookup_shelf_life` 는 (item_id, storage) 조합으로 찾으므로 조회가 계속 None 이었다.
--
-- ⚠️ **임의 배수를 곱하지 않는다.** "냉장이니 ROOM × 2" 같은 규칙은 근거가 없다.
--    보관별로 통용 기준을 직접 적는다 — 냉장/냉동은 산패·해충을 늦추므로 상온보다 길다.
--
-- 적용:
--   psql -h 192.168.0.8 -U fbapp -d foodbudget -v ON_ERROR_STOP=1 \
--        -f docs/prd/migrations/2026-07-29f_shelf_life_staple_alt_storage.sql

BEGIN;
-- 상비품의 비표준 보관 — 냉장/냉동은 산패를 늦추므로 ROOM 값 이상이다.
-- 실측(2026-07-29) 유저 재고: 식용유 FRIDGE · 박력분 FRIDGE · 통깨 FREEZER.
-- ⚠️ 임의 배수를 곱하지 않는다. 보관별로 통용 기준을 직접 적는다.
INSERT INTO public.shelf_life_ref (source, food_category, item_name, storage,
                                   days_min, days_max, note, item_id)
SELECT 'CURATED', im.category, im.canonical_name, v.storage, v.dmin, v.dmax, v.note, im.item_id
  FROM item_master im
  JOIN (VALUES
        ('식용유','FRIDGE', 365, 730, '냉장 시 산패 지연 — 굳을 수 있으나 품질 이상 아님'),
        ('올리브유','FRIDGE', 365, 730, '냉장 시 산패 지연 — 굳을 수 있으나 품질 이상 아님'),
        ('참기름','FRIDGE', 180, 365, '냉장 시 산패 지연'),
        ('밀가루','FRIDGE', 365, 730, '냉장 시 해충·산패 방지'),
        ('밀가루','FREEZER', 730, 1095, '냉동 장기 보관'),
        ('박력분','FRIDGE', 365, 730, '냉장 시 해충·산패 방지'),
        ('박력분','FREEZER', 730, 1095, '냉동 장기 보관'),
        ('강력분','FRIDGE', 365, 730, '냉장 시 해충·산패 방지'),
        ('통깨','FREEZER', 365, 730, '냉동 시 산패 지연'),
        ('깨소금','FREEZER', 365, 730, '냉동 시 산패 지연'),
        ('고춧가루','FRIDGE', 180, 365, '냉장 보관 가능 — 색·향 보존')
       ) AS v(nm, storage, dmin, dmax, note) ON v.nm = im.canonical_name
 WHERE NOT EXISTS (SELECT 1 FROM public.shelf_life_ref x
                    WHERE x.item_id = im.item_id AND x.storage = v.storage);
COMMIT;

-- 적용 확인:
--   select item_name, storage, days_min, days_max from public.shelf_life_ref
--    where item_name in ('식용유','박력분','통깨') order by 1,2;
--
-- 롤백:
--   delete from public.shelf_life_ref where source='CURATED' and note like '냉장 시%' ;
--   delete from public.shelf_life_ref where source='CURATED' and note like '냉동 %';
