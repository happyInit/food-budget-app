-- 2026-08-02m — recipebook.user_recipe 에 source_creator(유튜브 채널명) 추가
--
-- ## 무엇을 / 왜
-- 영상 추출 레시피의 **출처(유튜브 채널명)**를 상세페이지 '출처' 표기에 쓴다.
-- 영상 서비스가 oEmbed author_name 을 이미 넘겨주는데(#475) 저장할 자리가 없었다.
--
-- 기존 행(수동작성·과거 추출)은 NULL 로 남는다 — 코드가 NULL 을 정상 처리(출처 미표시).
-- 추가 컬럼이라 backfill·다운타임 없음. IF NOT EXISTS 로 재실행 안전(멱등).

ALTER TABLE recipebook.user_recipe ADD COLUMN IF NOT EXISTS source_creator text;
