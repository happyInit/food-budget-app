-- CRF 색상어 단독 재료 행 제거 (백로그 §1.14) — 2026-07-30
--
-- ── 무엇이 문제인가 ────────────────────────────────────────────────────────────
-- CRF 백필이 색상 **수식어**를 별도 재료 행으로 만들었다. 실측: 원문 `파프리카(빨간색, 노란색)`
-- 에서 `파프리카` 뒤에 `빨간색`·`노란색` 이 각각 독립 행으로 들어갔다.
--
-- `item_id` 가 안 붙어 **재료비 비용은 0**이지만, 레시피 상세 API 가 `ingredient_name` 을
-- **필터 없이** 반환하므로(`services/recipe/app/queries.py:147` — item_id·ner_status 조건 없음)
-- **유저 화면에 재료로 보인다.** 레시피 16875 의 실제 재료 목록:
--
--     seq  9  파프리카     item_id 37
--     seq 10  빨간색       null      ← 재료가 아니다
--     seq 11  노란색       null      ← 재료가 아니다
--
-- 재생산은 `backfill_ner_raw_ingredients.py` 의 `_COLOR_ONLY` 필터로 막았다. 이 마이그레이션은
-- **이미 들어간 행을 치운다**(필터는 앞으로만 막는다).
--
-- ── 삭제 조건을 좁게 거는 이유 ─────────────────────────────────────────────────
-- 🔴 `%색%` 로 지우면 **실제 재료가 대량으로 날아간다** — 실측: 자색양파(6) · 갈색설탕(5) ·
--    자색고구마(4) · 대파 녹색부분(2) · 적색 파프리카(2) · 노란색 파프리카(2) · 삼색파프리카(1)
--    은 전부 매칭에 성공한 정상 재료다. 그래서 세 조건을 **모두** 건다:
--      ① 이름이 색상어 **단독**(정규식 완전일치)
--      ② `ner_status = 'NER_PARSED'` — CRF 백필이 만든 행만
--      ③ `item_id IS NULL` — 품목이 붙었다면 재료로 인정된 것이므로 건드리지 않는다
--
-- ── 되돌리기 ───────────────────────────────────────────────────────────────────
-- 백필은 `_ALREADY`(이미 NER_PARSED 인 레시피 제외)로 재실행 시 건너뛰므로 **자동 복구되지
-- 않는다.** 다만 지우는 것이 재료가 아닌 행이라 복구할 이유가 없고, 원문은
-- `ingredient_raw`(RAW 행)에 그대로 남아 있어 정보 자체는 유실되지 않는다.
--
-- 재실행 안전: 대상이 없으면 0행 삭제(무동작).

BEGIN;

-- 삭제 전 확인 — 무엇이 지워지는지 남긴다
SELECT recipe_id, seq, ingredient_name, ner_status, item_id
  FROM recipe_ingredient
 WHERE ingredient_name ~ '^(빨간|노란|파란|초록|검은|하얀|보라|주황|분홍|갈|자|적|청|황|녹|백|흑|회|남)색$'
   AND ner_status = 'NER_PARSED'
   AND item_id IS NULL
 ORDER BY recipe_id, seq;

DELETE FROM recipe_ingredient
 WHERE ingredient_name ~ '^(빨간|노란|파란|초록|검은|하얀|보라|주황|분홍|갈|자|적|청|황|녹|백|흑|회|남)색$'
   AND ner_status = 'NER_PARSED'
   AND item_id IS NULL;

-- 검증 — 남은 색상어 단독 행이 0이어야 하고, 실제 재료는 그대로여야 한다
SELECT
  (SELECT count(*) FROM recipe_ingredient
    WHERE ingredient_name ~ '^(빨간|노란|파란|초록|검은|하얀|보라|주황|분홍|갈|자|적|청|황|녹|백|흑|회|남)색$'
      AND ner_status = 'NER_PARSED' AND item_id IS NULL)          AS color_only_left,
  (SELECT count(*) FROM recipe_ingredient
    WHERE ingredient_name IN ('자색양파','갈색설탕','자색고구마','삼색파프리카'))  AS real_kept;

COMMIT;
