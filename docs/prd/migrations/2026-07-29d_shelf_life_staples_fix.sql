-- 상비 시드 정정 (2026-07-29c 후속) — 과대 주장 6종 교정 + note 문구 중립화.
--
-- ── 왜 고치나 ───────────────────────────────────────────────────────────────
-- 2026-07-29c 에서 15종을 days NULL(기한 없음)로 넣었는데, **6종은 근거가 과했다**:
--   · 물엿·올리고당 — 당류지만 점도·색 변화가 실제로 일어난다(품질유지기한 표시 대상).
--   · 청주·맛술     — 개봉 후 산화한다.
--   · 다시다·치킨스톡 — 유지(油脂) 성분이 있어 장기 보관 시 산패 가능.
-- 이들은 "기한 없음"이 아니라 **"매우 김"** 이 정확하다. 2~3년 값을 준다.
--
-- ── note 문구 중립화 ────────────────────────────────────────────────────────
-- note 는 현재 API 로 노출되지 않지만(내부 전용), "무기한" 이라는 단정은
-- ① 포장의 **품질유지기한** 표기와 개념이 달라 다음 사람이 오독하기 쉽고
-- ② 나중에 노출 경로가 생기면 그대로 유저에게 새어 유저가 "앱이 틀렸다"고 읽는다.
-- → 식품에 대한 단정("무기한") 대신 **우리 처리 방식**("기한 추정 대상 아님")으로 바꾼다.
--
-- ⚠️ UI 방침(2026-07-29 결정): 이런 품목은 화면에 **아무 문구도 표시하지 않는다**.
--    "무기한"·"기한 관리 안 함" 같은 배지를 붙이지 않는다 — 도발적이고 반박 가능하다.
--    대신 재고 화면 어딘가에 **작은 일반 안내**("포장 표기를 확인하세요")를 둔다(프론트 과제).
--    days NULL 기록 자체는 유지한다 — "모름(행 없음)"과 "추정 대상 아님(행 있고 NULL)"의
--    구분은 커버리지 측정·AI 초안 대상 선정·검수 우선순위가 의존하는 내부 정보다.
--
-- 적용:
--   psql -h 192.168.0.8 -U fbapp -d foodbudget -v ON_ERROR_STOP=1 \
--        -f docs/prd/migrations/2026-07-29d_shelf_life_staples_fix.sql

BEGIN;

-- ① 과대 주장 6종 — days NULL → 실제 장기값
UPDATE public.shelf_life_ref SET days_min = 730, days_max = 1095,
       note = '장기 — 개봉 후 점도·색 변화 가능'
 WHERE source = 'CURATED' AND days_max IS NULL AND item_name IN ('물엿', '올리고당');

UPDATE public.shelf_life_ref SET days_min = 365, days_max = 730,
       note = '장기 — 개봉 후 산화'
 WHERE source = 'CURATED' AND days_max IS NULL AND item_name IN ('청주', '맛술');

UPDATE public.shelf_life_ref SET days_min = 365, days_max = 730,
       note = '장기 — 유지 성분 산패 가능'
 WHERE source = 'CURATED' AND days_max IS NULL AND item_name IN ('다시다', '치킨스톡');

-- ② 남은 기한 없음 품목 — note 를 중립 문구로. 값(NULL)은 그대로 둔다.
UPDATE public.shelf_life_ref
   SET note = '기한 추정 대상 아님 — 포장의 품질유지기한 표기를 따른다'
 WHERE source = 'CURATED' AND days_min IS NULL AND days_max IS NULL;

COMMIT;

-- 적용 확인:
--   select item_name, days_min, days_max, note from public.shelf_life_ref
--    where source='CURATED' and days_max is null order by 1;      -- 9종만 남아야 한다
--   select item_name, days_min, days_max from public.shelf_life_ref
--    where item_name in ('물엿','올리고당','청주','맛술','다시다','치킨스톡');
--
-- 롤백: 2026-07-29c 의 원래 값으로 되돌리려면 해당 6종을 days NULL 로, note 를 '무기한%' 로.
