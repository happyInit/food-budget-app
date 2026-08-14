-- 2026-08-14 — EKS 스키마 캐치업 (A3 선행)
--
-- ── 왜 필요한가 ──────────────────────────────────────────────────────────────
-- A1 은 EKS PG 를 `schema-production.sql` 로 세웠다. 그런데 온프렘은 그 위에
-- `docs/prd/migrations/*.sql` 15개가 **더 얹힌 상태**이고, 그 산물이
-- `schema-production.sql` 로 **접혀 들어간 적이 없다.**
-- ⇒ 두 클러스터 스키마가 41개 컬럼만큼 어긋나 있었다(2026-08-14 A3 리허설 실측):
--      · 테이블 5개 통째 부재 (컬럼 37개)
--      · 기존 테이블의 컬럼 4개 부재
--    EKS 에만 있는 객체는 **0개** — 즉 EKS 는 온프렘의 진부분집합이었다.
--
-- 🔴 **이걸 안 고치고 A3 를 하면 두 번 터진다.**
--    ① `pg_dump --data-only` 복원이 없는 테이블에서 죽는다.
--    ② 설령 그 테이블을 빼고 복원해도, **EKS 앱이 실제로 그 객체를 읽는다**:
--         public.item_unit_weight              ← services/{recipe,chat,video}
--         public.price_anomaly                 ← services/price
--         public.item_master.density_g_per_ml  ← services/{recipe,chat,video}
--         public.recipe_review_summary.caution ← services/recipe
--       빠지면 배포는 성공하고 **쿼리만 런타임에 죽는다** — 컷오버 후에 발견된다.
--
-- ── 파이프라인 전용 객체도 같이 만드는 이유 ─────────────────────────────────
-- price_baseline · price_alert_sent · pantry_expire_backfill_log 와
-- recipe_review_summary.{summary_kind,summary_model} 은 지금 EKS 앱이 안 읽는다.
-- 그래도 만든다 — 근거 셋:
--   ① 총량이 1MB 미만이다(최대가 price_baseline 5,792행/952kB). 아끼는 게 없다.
--   ② 부분만 만들면 *"EKS 는 온프렘의 진부분집합"* 이라는 단순한 명제가 깨져서,
--      앞으로 매 작업마다 "이건 EKS 에 있나?" 를 개별로 따져야 한다.
--   ③ A5(파이프라인 적재)에서 반드시 다시 필요해진다 — price_baseline 은
--      최저가 알림(P0)의 기준선 그 자체다.
--
-- ── 멱등 ────────────────────────────────────────────────────────────────────
-- 전부 IF NOT EXISTS / DO 블록이다. **온프렘에 돌리면 전건 no-op** 이므로
-- C-83(온프렘 형상 동결)을 어기지 않는다. DDL 원문은 온프렘 pg_dump --schema-only
-- 에서 그대로 떴다(손으로 다시 쓰면 인덱스·제약·기본값을 놓친다).
--
-- 적용:  psql -U postgres -d foodbudget -f 2026-08-14_eks_schema_catchup.sql

BEGIN;

-- ============================================================================
-- 1) 없는 테이블 5종
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.item_unit_weight (
    item_id bigint NOT NULL,
    unit    text   NOT NULL,
    grams   numeric NOT NULL,
    src     text,
    CONSTRAINT item_unit_weight_pkey PRIMARY KEY (item_id, unit),
    CONSTRAINT item_unit_weight_item_id_fkey FOREIGN KEY (item_id)
        REFERENCES public.item_master(item_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS item_unit_weight_item_idx
    ON public.item_unit_weight USING btree (item_id);

CREATE TABLE IF NOT EXISTS public.price_baseline (
    item_id     bigint  NOT NULL,
    as_of       date    NOT NULL,
    window_days integer DEFAULT 30 NOT NULL,
    mean_100g   numeric NOT NULL,
    stddev_100g numeric NOT NULL,
    min_100g    numeric,
    obs_count   integer NOT NULL,
    computed_at timestamptz DEFAULT now() NOT NULL,
    source      text    NOT NULL,
    CONSTRAINT price_baseline_pkey PRIMARY KEY (item_id, source, as_of),
    CONSTRAINT price_baseline_source_check CHECK (source = ANY (ARRAY['kurly'::text, 'oasis'::text])),
    CONSTRAINT price_baseline_item_id_fkey FOREIGN KEY (item_id)
        REFERENCES public.item_master(item_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS price_baseline_asof_idx
    ON public.price_baseline USING btree (as_of DESC);
COMMENT ON COLUMN public.price_baseline.source IS
    '소매 소스. 기준선은 (품목, 소스)별로 따로 잡는다 — 두 소매의 100g 단가가 중앙값 41.9% 다르고, 합치면 σ가 중앙값 2.08배 부풀어 z가 절반이 되어 탐지가 죽는다(실측 2026-07-29).';

-- 🔴 `id` 는 온프렘과 **똑같이 bigserial** 이다. IDENTITY 가 더 낫지만(#685: bigserial 은
--    시퀀스 GRANT 를 따로 줘야 하고 빠뜨리면 INSERT 가 조용히 실패한다) 여기서는 쓰면 안 된다 —
--    A3 의 `pg_dump --data-only` 가 `setval('public.price_anomaly_id_seq', …)` 를 뱉는데
--    IDENTITY 로 만들면 그 이름의 시퀀스가 없어 **컷오버 창 안에서 복원이 깨진다.**
--    ⇒ 스키마 개선은 이관 뒤에. 지금은 온프렘과 한 글자도 다르지 않은 쪽이 옳다.
--    대신 #685 의 교훈은 아래 GRANT 절에서 **시퀀스 권한을 명시**하는 것으로 갚는다.
CREATE TABLE IF NOT EXISTS public.price_anomaly (
    id                bigserial,
    item_id           bigint  NOT NULL,
    detected_on       date    NOT NULL,
    source            text    NOT NULL,
    retail_product_id bigint  NOT NULL,
    crawled_at        timestamptz NOT NULL,
    price             numeric NOT NULL,
    price_100g        numeric NOT NULL,
    z_score           numeric NOT NULL,
    baseline_mean     numeric NOT NULL,
    baseline_stddev   numeric NOT NULL,
    is_record_low     boolean DEFAULT false NOT NULL,
    discount_rate     integer,
    published_at      timestamptz,
    created_at        timestamptz DEFAULT now() NOT NULL,
    drop_pct          numeric,
    CONSTRAINT price_anomaly_pkey PRIMARY KEY (id),
    CONSTRAINT price_anomaly_item_id_detected_on_source_key UNIQUE (item_id, detected_on, source),
    CONSTRAINT price_anomaly_source_check CHECK (source = ANY (ARRAY['kurly'::text, 'oasis'::text])),
    CONSTRAINT price_anomaly_item_id_fkey FOREIGN KEY (item_id)
        REFERENCES public.item_master(item_id) ON DELETE CASCADE,
    CONSTRAINT price_anomaly_retail_product_id_fkey FOREIGN KEY (retail_product_id)
        REFERENCES public.retail_product(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS price_anomaly_unpublished_idx
    ON public.price_anomaly USING btree (created_at) WHERE (published_at IS NULL);
COMMENT ON COLUMN public.price_anomaly.drop_pct IS
    '기준선 대비 하락률(%). z와 함께 판정 게이트이자 노출 정렬 키 — z 단독은 σ 극소 품목을 상위로 올려 체감 없는 급락을 뽑는다(실측).';

CREATE TABLE IF NOT EXISTS public.price_alert_sent (
    anomaly_id      bigint NOT NULL,
    user_id         bigint NOT NULL,
    notification_id bigint,
    sent_at         timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT price_alert_sent_pkey PRIMARY KEY (anomaly_id, user_id),
    CONSTRAINT price_alert_sent_anomaly_id_fkey FOREIGN KEY (anomaly_id)
        REFERENCES public.price_anomaly(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS price_alert_sent_user_idx
    ON public.price_alert_sent USING btree (user_id, sent_at DESC);

CREATE TABLE IF NOT EXISTS pantry.pantry_expire_backfill_log (
    pantry_item_id bigint NOT NULL,
    new_expire_at  date   NOT NULL,
    source         text   NOT NULL,
    applied_at     timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT pantry_expire_backfill_log_pkey PRIMARY KEY (pantry_item_id)
);

-- ============================================================================
-- 2) 기존 테이블의 없는 컬럼 4개 — 전부 nullable·기본값 없음(순수 덧셈)
-- ============================================================================

ALTER TABLE public.item_master           ADD COLUMN IF NOT EXISTS density_g_per_ml numeric;
ALTER TABLE public.recipe_review_summary ADD COLUMN IF NOT EXISTS caution       text;
ALTER TABLE public.recipe_review_summary ADD COLUMN IF NOT EXISTS summary_kind  text;
ALTER TABLE public.recipe_review_summary ADD COLUMN IF NOT EXISTS summary_model text;

-- CHECK 은 IF NOT EXISTS 가 없다 — 카탈로그로 판정한다.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.recipe_review_summary'::regclass
          AND conname  = 'recipe_review_summary_summary_kind_check'
    ) THEN
        ALTER TABLE public.recipe_review_summary
            ADD CONSTRAINT recipe_review_summary_summary_kind_check
            CHECK (summary_kind = ANY (ARRAY['llm'::text, 'template'::text]));
    END IF;
END $$;

-- ============================================================================
-- 3) GRANT — 🔴 명시해야 한다
-- ============================================================================
-- `schema-roles.sql` 의 자동 반영 경로 두 개가 여기서는 **둘 다 안 걸린다**:
--   · `GRANT … ON ALL TABLES IN SCHEMA public` 은 실행 시점 스냅샷이다(미래 테이블 제외).
--   · `ALTER DEFAULT PRIVILEGES FOR ROLE fbapp / svc_pipeline` 은 **생성 롤 단위**인데
--     EKS 의 public 테이블 소유자는 `postgres` 다(실측). 그 둘 중 어느 쪽도 아니다.
-- ⇒ 빠뜨리면 테이블은 생기고 앱만 permission denied 로 죽는다.
-- 부여 형태는 EKS 의 기존 public 테이블 실측값과 동일하게 맞춘다
--   (reader = SELECT · writer = INSERT/UPDATE/DELETE · 시퀀스 reader SELECT/writer USAGE).

GRANT SELECT ON public.item_unit_weight, public.price_baseline,
                public.price_anomaly,    public.price_alert_sent
      TO mp_data_reader;

GRANT INSERT, UPDATE, DELETE ON public.item_unit_weight, public.price_baseline,
                                public.price_anomaly,    public.price_alert_sent
      TO mp_data_writer;

-- 🔴 시퀀스 권한 — bigserial 은 테이블 GRANT 를 **따라가지 않는다**(#685 가 정확히 이것이었다:
--    activity 쪽 시퀀스 USAGE 를 빠뜨려 노출 로그 INSERT 가 조용히 0건이었다).
--    이름을 박지 않고 카탈로그에서 찾는다 — 이름 오타면 GRANT 가 아니라 스크립트가 죽어야 한다.
DO $$
DECLARE seq regclass := pg_get_serial_sequence('public.price_anomaly', 'id');
BEGIN
    IF seq IS NULL THEN
        RAISE EXCEPTION 'price_anomaly.id 에 시퀀스가 없다 — bigserial 이 아닌 형태로 만들어졌다';
    END IF;
    EXECUTE format('GRANT SELECT ON SEQUENCE %s TO mp_data_reader', seq);
    EXECUTE format('GRANT USAGE  ON SEQUENCE %s TO mp_data_writer', seq);
END $$;

-- 🔴 pantry.pantry_expire_backfill_log 에는 GRANT 를 주지 않는다.
--    `schema-roles.sql` 이 명시한 대로 **일회성 마이그레이션 SQL 만** 쓰는 표다.
--    서비스에 권한을 주면 그 표가 앱 표로 오해되어 나중에 참조가 생긴다.

COMMIT;

-- ============================================================================
-- 검증
-- ============================================================================
-- 온프렘·EKS 에서 각각 돌려 두 출력이 같아야 한다:
--   select table_schema||'.'||table_name||'.'||column_name
--     from information_schema.columns
--    where table_schema not in ('pg_catalog','information_schema') order by 1;
