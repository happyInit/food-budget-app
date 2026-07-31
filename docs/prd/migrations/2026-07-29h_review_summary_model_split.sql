-- 리뷰 집계표 — 요약 모델 컬럼 분리 (#10).
--
-- ── 왜 필요한가 ─────────────────────────────────────────────────────────────
-- `recipe_review_summary` 에 AI 산출물이 **둘**인데(`positive_rate` = 감정분류 집계,
-- `summary` = 자유 요약) 모델 컬럼은 **하나**다. 두 배치가 같은 칸을 쓰면 나중에 덮은 쪽만 남는다.
--
-- 핸드오프 §4.1 이 model 컬럼의 용도를 *"모델 교체 시 재실행 대상을 쿼리 한 줄로 특정"* 이라고
-- 명시했는데, 요약 배치가 덮어쓰면 **"긍정비율을 어느 모델로 냈나"를 알 수 없게 된다.**
--
-- 실측(2026-07-29): 감정분류 완주 후 `model` 이 전부 `apac.amazon.nova-micro-v1:0` 이었고,
-- 요약 배치가 그대로 돌면 3,086행이 `claude-3-5-sonnet` 으로 덮일 상황이었다.
--
-- ── 처방 ────────────────────────────────────────────────────────────────────
--   · `model`         → **감정분류 모델**(기존 의미 유지)
--   · `summary_model` → **요약 모델**(신규)
-- 건당 감정 라벨의 모델은 `recipe_review_sentiment.model` 에도 있으므로 재실행 대상 특정은
-- 그쪽이 정본이다. 이 컬럼은 집계 시점의 스냅샷이다.
--
-- 적용:
--   psql -h 192.168.0.8 -U fbapp -d foodbudget -v ON_ERROR_STOP=1 \
--        -f docs/prd/migrations/2026-07-29h_review_summary_model_split.sql

BEGIN;

ALTER TABLE recipe_review_summary ADD COLUMN IF NOT EXISTS summary_model text;

COMMENT ON COLUMN recipe_review_summary.model IS
  '감정분류(positive_rate) 산출 모델. 요약 모델은 summary_model 을 볼 것 — 산출물이 둘이라 컬럼도 둘이다.';
COMMENT ON COLUMN recipe_review_summary.summary_model IS
  '요약(summary) 생성 모델. 실측 확정 = apac.anthropic.claude-3-5-sonnet-20241022-v2:0 (2026-07-29).';

COMMIT;

-- 적용 확인:
--   \d recipe_review_summary
--   select model, summary_model, count(*) from recipe_review_summary group by 1,2;
--
-- 롤백:
--   ALTER TABLE recipe_review_summary DROP COLUMN summary_model;
