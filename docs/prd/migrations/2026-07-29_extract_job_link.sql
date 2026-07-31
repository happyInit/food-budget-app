-- 영상→레시피(#7·#11) 추적성 보완 — extract_job 에 산출물 링크 1컬럼 추가.
--
-- ⚠️ 이 파일만 **기존 테이블을 변경**한다(나머지 마이그레이션은 전부 신규 생성).
--    다만 nullable + IF NOT EXISTS + DEFAULT 없음 이라 테이블 재작성이 일어나지 않는다
--    (PG11+ 는 DEFAULT 있는 ADD COLUMN 도 즉시지만, 여기선 아예 없다). 잠금은 순간이다.
--
-- 왜 필요한가 — 현재 구조로는 답할 수 없는 질문이 셋 있다:
--   1. "이 job 이 실제로 레시피를 만들었나?"
--      status='DONE' 인데 user_recipe 가 없어도 감지할 방법이 없다 → 조용한 실패.
--   2. "이 job 을 재처리하면 갱신인가 신규 생성인가?"
--      연결이 없어 판단 불가 → 같은 영상으로 레시피가 중복 생성될 수 있다.
--   3. 사후 감사 — 어떤 추출이 어떤 결과를 냈는지 되짚을 수 없다.
--
--   역방향(레시피 → 영상)은 user_recipe.source_url 로 이미 가능하다. 순방향만 비어 있었다.
--
-- 관례: recipebook.shared_recipe 가 이미 같은 방식으로 user_recipe(id) 를 참조한다.
--       다만 거기는 CASCADE(공유는 원본과 생사를 같이함), 여기는 SET NULL 이다 —
--       유저가 레시피를 지워도 **추출 시도 기록은 남아야** 재처리·감사가 가능하기 때문.
--
-- 적용:
--   psql -h 192.168.0.8 -U fbapp -d foodbudget -f docs/prd/migrations/2026-07-29_extract_job_link.sql

BEGIN;

ALTER TABLE recipebook.extract_job
  ADD COLUMN IF NOT EXISTS user_recipe_id bigint
    REFERENCES recipebook.user_recipe(id) ON DELETE SET NULL;

COMMENT ON COLUMN recipebook.extract_job.user_recipe_id IS
  '추출 성공 시 생성된 레시피. NULL = 미완료·실패, 또는 유저가 레시피를 삭제함';

-- 완료했다면서 산출물이 없는 job 스캔 — 조용한 실패 탐지용.
CREATE INDEX IF NOT EXISTS extract_job_orphan_done_idx
  ON recipebook.extract_job (created_at)
  WHERE status = 'DONE' AND user_recipe_id IS NULL;

COMMIT;

-- 적용 확인:
--   \d recipebook.extract_job
--   select count(*) from recipebook.extract_job
--    where status = 'DONE' and user_recipe_id is null;   -- 기존 행은 전부 여기 잡힌다(정상)
--
-- ⚠️ 기존 DONE 행은 전부 user_recipe_id IS NULL 이다(소급 채움 불가 — 어느 레시피인지 알 수 없다).
--    이 인덱스의 "조용한 실패 탐지"는 **이 마이그레이션 이후 생성된 job** 부터 유효하다.
--
-- 롤백:
--   DROP INDEX IF EXISTS recipebook.extract_job_orphan_done_idx;
--   ALTER TABLE recipebook.extract_job DROP COLUMN IF EXISTS user_recipe_id;
