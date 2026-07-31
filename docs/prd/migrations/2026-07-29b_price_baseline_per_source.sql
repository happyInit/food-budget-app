-- 가격 기준선 교정 — 소스별 분리 (#9). 2026-07-29_price_anomaly.sql 의 후속 정정.
--
-- ⚠️ 기존 마이그레이션 파일을 고치지 않고 **새 파일**로 낸다(핸드오프 §11 G4 규칙).
--
-- ── 왜 고쳐야 하는가 (실측 근거) ─────────────────────────────────────────────
-- 원설계는 price_baseline PK 를 (item_id, as_of) 로 두어 **컬리·오아시스를 한 기준선에
-- 합쳤다.** 근거는 "100g 로 정규화하면 같은 축에 쌓이므로 baseline 이 2배 속도로 축적된다"
-- 였는데, 실 DB 측정 결과 **전제가 성립하지 않는다.**
--
--   · 두 소스가 모두 파는 175개 품목에서 같은 품목의 100g 단가가
--     **중앙값 41.9% 차이** (61%가 30%↑, 45%가 50%↑ 차이)
--   · 소스를 합치면 σ 가 **중앙값 2.08배** 부푼다
--     (125개 중 53%가 2배↑, 31%가 5배↑ 부풀었다)
--
-- z = (x − μ) / σ 이므로 **σ 가 2배면 모든 z 가 절반**이 된다. z ≤ −2.0 임계에서
-- 실제 −2.4 짜리 급락이 −1.2 로 찍혀 **탐지되지 않는다.** 표본이 2배가 되는 이득은
-- μ·σ 추정의 *정밀도*에 그치지만, σ 부풀림은 **탐지 자체를 무력화**한다. 교환이 성립하지 않는다.
--
-- 두 소매가 같은 품목을 다른 가격대에 파는 것은 아티팩트가 아니라 **사실**이다
-- (매장 포지셔닝). 그래서 "평상시 가격"도 소스별로 따로 정의되어야 한다.
--
-- ── 지금 고치는 이유 ─────────────────────────────────────────────────────────
-- 세 테이블 모두 **0행**이다. 지금은 무손실이지만, 기준선이 한 번 쌓이기 시작하면
-- 재계산·백필 비용이 생긴다.
--
-- 적용:
--   psql -h 192.168.0.8 -U fbapp -d foodbudget -v ON_ERROR_STOP=1 \
--        -f docs/prd/migrations/2026-07-29b_price_baseline_per_source.sql

BEGIN;

-- 안전장치 — 데이터가 있으면 멈춘다. 있는 상태로 PK 를 바꾸면 의미가 달라진 행이 남는다.
DO $$
BEGIN
  IF (SELECT count(*) FROM price_baseline) > 0 THEN
    RAISE EXCEPTION E'\n\nprice_baseline 에 이미 % 행이 있다. 소스별 재계산 후 적용할 것.\n',
      (SELECT count(*) FROM price_baseline);
  END IF;
END $$;

-- ── ① price_baseline — 소스별 기준선 ────────────────────────────────────────
-- 기준선의 단위는 "품목"이 아니라 **(품목, 소스)** 다.
ALTER TABLE price_baseline ADD COLUMN IF NOT EXISTS source text;

-- 빈 테이블이므로 NOT NULL·CHECK 를 바로 건다. price_anomaly.source 와 동일한 도메인.
UPDATE price_baseline SET source = 'kurly' WHERE source IS NULL;   -- 0행(방어적)
ALTER TABLE price_baseline ALTER COLUMN source SET NOT NULL;

ALTER TABLE price_baseline DROP CONSTRAINT IF EXISTS price_baseline_source_check;
ALTER TABLE price_baseline ADD  CONSTRAINT price_baseline_source_check
  CHECK (source IN ('kurly','oasis'));

-- PK 재정의: (item_id, as_of) → (item_id, source, as_of)
ALTER TABLE price_baseline DROP CONSTRAINT IF EXISTS price_baseline_pkey;
ALTER TABLE price_baseline ADD  CONSTRAINT price_baseline_pkey
  PRIMARY KEY (item_id, source, as_of);

COMMENT ON COLUMN price_baseline.source IS
  '소매 소스. 기준선은 (품목, 소스)별로 따로 잡는다 — 두 소매의 100g 단가가 중앙값 41.9% '
  '다르고, 합치면 σ가 중앙값 2.08배 부풀어 z가 절반이 되어 탐지가 죽는다(실측 2026-07-29).';

-- ── ② price_anomaly — 근거 스냅샷에 하락률 추가 ─────────────────────────────
-- 알림 문구가 "▼26% 급락"으로 나가는데 그 수치가 테이블에 없어 근거 재현이 불완전했다.
-- 탐지 배치는 z 단독으로 판정하지 않는다 — σ가 극소한 품목이 z 상위를 차지해 "체감 없는
-- 급락"이 잡히므로 **최소 하락률(8%) 동시 충족**을 요구하고, 정렬도 체감(하락률) 순이다.
-- 그 게이트에 쓰인 값이 남아야 임계 재조정이 가능하다.
ALTER TABLE price_anomaly ADD COLUMN IF NOT EXISTS drop_pct numeric;

COMMENT ON COLUMN price_anomaly.drop_pct IS
  '기준선 대비 하락률(%). z와 함께 판정 게이트이자 노출 정렬 키 — z 단독은 σ 극소 품목을 '
  '상위로 올려 체감 없는 급락을 뽑는다(실측).';

COMMIT;

-- 적용 확인:
--   \d price_baseline    -- PK 가 (item_id, source, as_of) 인지
--   \d price_anomaly     -- drop_pct 존재
--
-- 롤백:
--   ALTER TABLE price_baseline DROP CONSTRAINT price_baseline_pkey;
--   ALTER TABLE price_baseline ADD  CONSTRAINT price_baseline_pkey PRIMARY KEY (item_id, as_of);
--   ALTER TABLE price_baseline DROP CONSTRAINT price_baseline_source_check;
--   ALTER TABLE price_baseline DROP COLUMN source;
--   ALTER TABLE price_anomaly  DROP COLUMN drop_pct;
