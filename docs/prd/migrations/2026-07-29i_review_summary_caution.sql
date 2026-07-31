-- 리뷰 집계표 — 주의사항 필드 분리 (#10).
--
-- ── 왜 필요한가 ─────────────────────────────────────────────────────────────
-- 소수의 부정 후기("물 양이 틀렸어요")를 **요약 표본에 강제로 끼워 넣으면 비율이 왜곡된다** —
-- 후기 300건 중 부정 2건(0.7%)을 15건 표본에 3건(20%) 넣으면 **30배 과대대표**가 되어
-- 좋은 레시피가 부당하게 나쁘게 보인다.
--
-- 그렇다고 버리면 유용한 경고가 사라진다. **한 칸에 두 성격을 섞은 것이 문제**이므로 칸을 나눈다:
--   · `summary` — 전체 논조(균등 표본 + 전수 분포 주입). 비율에 충실.
--   · `caution` — **부정 라벨 후기에서만** 뽑은 주의사항. "일부 후기" 프레이밍이 내장돼
--                 소수의견임이 드러나므로 과대대표되지 않는다.
--
-- 실측(2026-07-29): 대상 2,195개 중 **1,042개**가 부정 후기를 갖는다(총 2,740건, 평균 2.6건).
-- 부정 후기 수가 적어 입력 토큰이 작고, 별도 호출 비용이 건당 약 3원이다.
--
-- 적용:
--   psql -h 192.168.0.8 -U fbapp -d foodbudget -v ON_ERROR_STOP=1 \
--        -f docs/prd/migrations/2026-07-29i_review_summary_caution.sql

BEGIN;

ALTER TABLE recipe_review_summary ADD COLUMN IF NOT EXISTS caution text;
-- 요약 생성 방식 — LLM 인지 집계 템플릿인지. 리뷰가 적은 레시피는 LLM 을 쓰지 않는다(§아래).
ALTER TABLE recipe_review_summary ADD COLUMN IF NOT EXISTS summary_kind text
  CHECK (summary_kind IN ('llm', 'template'));

COMMENT ON COLUMN recipe_review_summary.caution IS
  '부정 라벨 후기에서만 뽑은 주의사항(있을 때만). summary 와 분리한 이유 = 소수의견을 '
  '요약 표본에 섞으면 비율이 왜곡되기 때문. UI 는 "일부 후기" 로 표기할 것.';
COMMENT ON COLUMN recipe_review_summary.summary_kind IS
  'llm=모델 생성(후기 10건 이상) · template=집계 기반 문장(1~9건). '
  '후기 3건을 2문장으로 압축하면 정보가 줄어 LLM 을 쓰지 않는다 — 대신 화면이 비지 않게 채운다.';

COMMIT;

-- 적용 확인:
--   select summary_kind, count(*), count(caution) from recipe_review_summary group by 1;
--
-- 롤백:
--   ALTER TABLE recipe_review_summary DROP COLUMN caution, DROP COLUMN summary_kind;
