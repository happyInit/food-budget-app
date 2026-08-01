-- 상비 양념·장류 소비기한 큐레이션 시드 (ai-spec §6 — CURATED 확장).
--
-- ── 왜 AI 초안이 아니라 수작업인가 ──────────────────────────────────────────
-- 실측(2026-07-29): pantry_item 124행 중 expire_at NULL 49행. 그중 소비기한 미커버가 원인인
-- 29건인데, **분해하니 15건이 상비 양념**이었다(소금 4 · 설탕 2 · 후추 2 · 식용유 · 들기름 ·
-- 참치액젓 · 통깨 …). 신선식품은 8건뿐이다.
--
-- 그리고 이 구간이야말로 AI 가 가장 크게 틀린다 — nova-micro 초안 실측:
--     후추 FREEZER 6~12일 · 된장 FREEZER 1~6일 · 전분 FREEZER 6~12일 · 호두 FREEZER 6~12일
-- 상온 보관이 정상인 건조·발효 식품에 짧은 냉장/냉동 창을 붙이고 ROOM 은 통째로 비웠다.
-- 짧게 잡는 것이 안전해 보이지만 **반대다** — 멀쩡한 후추가 12일 뒤 임박 알림으로 떠서
-- 유저가 버린다. **식비 절약이라는 제품 목적과 정면으로 어긋난다.**
-- → 35개는 수작업 큐레이션이 더 정확하고 안전하며, AI 는 신선식품에만 쓴다.
--
-- ── days_min/days_max 를 NULL 로 두는 의미 ──────────────────────────────────
-- **행이 없음 = "모름"(미커버) / 행이 있고 days 가 NULL = "안다, 그리고 기한이 없다"(무기한).**
-- 런타임 동작은 둘 다 expire_at=NULL 로 같지만(estimate_expire_date 가 None 반환),
-- 시스템이 둘을 **구분**할 수 있게 된다 — UI 가 "무기한"으로 표시할지 기한칸을 숨길지
-- 나중에 정해도 데이터가 이미 받쳐준다. 소금에 억지 숫자를 넣는 것보다 정직하다.
--
-- ── 값의 근거 ───────────────────────────────────────────────────────────────
-- 무기한(NULL): 정제염·정제당·건조 향신료·식초·꿀·주류계 조미 — 미생물학적으로 상하지 않는다.
-- 유한값: 유지류(산패) · 개봉 후 냉장이 필요한 소스/장류 · 곡물가루(산패·해충).
--   보수적으로 잡되 **상비품을 임박 알림으로 만들지 않을 만큼**은 길게 둔다.
--
-- 적용:
--   psql -h 192.168.0.8 -U fbapp -d foodbudget -v ON_ERROR_STOP=1 \
--        -f docs/prd/migrations/2026-07-29c_shelf_life_staples.sql

BEGIN;

-- 멱등: 같은 (item_id, storage, source) 가 이미 있으면 넣지 않는다.
CREATE TEMP TABLE _staple_seed (
  item_id bigint, item_name text, storage text,
  days_min int, days_max int, note text
) ON COMMIT DROP;

INSERT INTO _staple_seed (item_id, item_name, storage, days_min, days_max, note) VALUES
  -- ── 무기한(days NULL) — 미생물학적으로 상하지 않는다 ──────────────────────
  (149, '소금',       'ROOM', NULL, NULL, '무기한 — 정제염은 상하지 않는다'),
  (99,  '함초소금',   'ROOM', NULL, NULL, '무기한'),
  (49,  '설탕',       'ROOM', NULL, NULL, '무기한 — 굳으면 풀어 쓴다'),
  (98,  '꿀',         'ROOM', NULL, NULL, '무기한 — 결정화는 변질 아님'),
  (64,  '물엿',       'ROOM', NULL, NULL, '무기한'),
  (97,  '올리고당',   'ROOM', NULL, NULL, '무기한'),
  (53,  '후추',       'ROOM', NULL, NULL, '무기한 — 향만 서서히 약해진다'),
  (127, '통후추',     'ROOM', NULL, NULL, '무기한'),
  (142, '흰후추',     'ROOM', NULL, NULL, '무기한'),
  (150, '식초',       'ROOM', NULL, NULL, '무기한 — 산도가 보존제'),
  (159, '발사믹식초', 'ROOM', NULL, NULL, '무기한'),
  (124, '청주',       'ROOM', NULL, NULL, '무기한'),
  (73,  '맛술',       'ROOM', NULL, NULL, '무기한'),
  (1312,'다시다',     'ROOM', NULL, NULL, '무기한 — 건조 분말'),
  (1449,'치킨스톡',   'ROOM', NULL, NULL, '무기한 — 건조/고형'),

  -- ── 유한값 — 산패·개봉 후 변질이 실제로 일어난다 ─────────────────────────
  (137, '식용유',     'ROOM', 180, 365, '개봉 후 산패 — 서늘한 곳'),
  (81,  '올리브유',   'ROOM', 180, 365, '개봉 후 산패 — 직사광선 피할 것'),
  (111, '참기름',     'ROOM',  90, 180, '개봉 후 산패가 빠르다'),
  (70,  '들기름',     'ROOM',  60, 120, '들기름은 참기름보다 더 빨리 산패'),
  (70,  '들기름',     'FRIDGE', 120, 240, '냉장 시 산패 지연'),
  (155, '밀가루',     'ROOM',  180, 365, '산패·해충 — 밀폐 보관'),
  (62,  '전분',       'ROOM',  365, 730, '건조 유지 시 장기'),
  (146, '고춧가루',   'FREEZER', 365, 730, '냉동이 표준 — 색·향 보존'),
  (146, '고춧가루',   'ROOM',  90, 180, '상온은 변색·해충 위험'),
  (59,  '통깨',       'ROOM',  90, 180, '산패 — 볶은 깨'),
  (115, '깨소금',     'ROOM',  90, 180, '산패'),

  -- 장류 — 냉장 보관이 표준. 개봉 후에도 길지만 무기한은 아니다.
  (126, '간장',       'ROOM',  365, 730, '개봉 후 냉장 권장'),
  (151, '국간장',     'ROOM',  365, 730, '개봉 후 냉장 권장'),
  (57,  '고추장',     'FRIDGE', 365, 730, '개봉 후 냉장'),
  (51,  '된장',       'FRIDGE', 365, 730, '개봉 후 냉장'),
  (679, '쌈장',       'FRIDGE', 180, 365, '개봉 후 냉장'),
  (114, '굴소스',     'FRIDGE', 180, 365, '개봉 후 냉장 필수'),
  (120, '케첩',       'FRIDGE', 180, 365, '개봉 후 냉장'),
  (78,  '마요네즈',   'FRIDGE',  30,  60, '개봉 후 냉장 — 유화 소스라 짧다'),

  -- 젓갈류 — 염도가 높아 길지만 냉장이 표준
  (441, '멸치액젓',   'FRIDGE', 365, 730, '고염 — 냉장'),
  (4027,'참치액젓',   'FRIDGE', 365, 730, '고염 — 냉장'),
  (281, '새우젓',     'FRIDGE', 180, 365, '냉장 필수');

INSERT INTO public.shelf_life_ref (source, food_category, item_name, storage,
                                   days_min, days_max, note, item_id)
SELECT 'CURATED', im.category, s.item_name, s.storage, s.days_min, s.days_max, s.note, s.item_id
  FROM _staple_seed s
  JOIN item_master im ON im.item_id = s.item_id
 WHERE NOT EXISTS (
   SELECT 1 FROM public.shelf_life_ref r
    WHERE r.item_id = s.item_id AND r.storage = s.storage AND r.source = 'CURATED'
 );

COMMIT;

-- 적용 확인:
--   select count(*) from public.shelf_life_ref where source='CURATED';
--   -- 무기한(명시) 품목
--   select item_name, storage from public.shelf_life_ref
--    where source='CURATED' and days_min is null and days_max is null order by 1;
--
-- 롤백:
--   delete from public.shelf_life_ref
--    where source='CURATED' and note like '무기한%' ;   -- 또는 fetched_at 기준으로 이번 배치분만
