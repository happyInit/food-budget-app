-- schema-roles.sql — 서비스별 DB 롤 + 최소권한 GRANT (멱등 DDL)
-- SSOT: docs/prd/schema-roles.md  (설계·근거·적용 순서·롤백)
-- 짝 파일: docs/prd/schema-production.sql (테이블 DDL). 이 파일은 "누가 무엇에 접근하는가"만 담는다.
--
-- 🔴 이 파일에는 비밀번호가 없다. 롤은 여기서 **NOLOGIN 으로** 만들어지고,
--    LOGIN 부여 + 비밀번호 설정은 CNPG `Cluster.spec.managed.roles` 가 K8s Secret 에서 주입한다.
--    (근거·YAML = schema-roles.md §4). 이 파일만 돌려서는 로그인 경로가 절대 열리지 않는다.
--
-- 🔴 데이터 티어는 `data` 가 아니라 `public` 이다. schema-production.md §0.3 은 `data` 스키마를
--    전제로 쓰였지만 실물에 `data` 는 없다(2026-08-09 실측). schema-production.sql:4-5 가 이미
--    같은 사실을 적어두고 있다. 이 파일은 실물(`public`)을 따른다.
--
-- 멱등: 롤 생성은 존재 확인 후에만. GRANT 는 본래 멱등. 재실행 안전.
--       ⚠️ 롤 속성(LOGIN/PASSWORD/CONNECTION LIMIT)은 여기서 **건드리지 않는다** —
--          CNPG 가 소유하므로 재실행이 CNPG 의 설정을 되돌리면 안 된다.
--
-- 🔴🔴 함정 — CNPG `spec.managed.roles[].inRoles` 는 **배타적**이다.
--    CNPG 는 선언한 멤버십 목록에 없는 멤버십을 **REVOKE 한다**. 이 파일의
--    `GRANT mp_data_reader TO svc_*` 는 전부 멤버십이므로, CNPG spec 의 `inRoles` 에
--    똑같이 적지 않으면 다음 reconcile 에서 조용히 회수돼 **읽기가 죽는다**.
--    두 곳을 항상 같이 고칠 것 (대조표 = schema-roles.md §4.2).
--
-- 실행:
--   psql -U postgres -d foodbudget -v ON_ERROR_STOP=1 -f docs/prd/schema-roles.sql
--   (클러스터에서는  kubectl -n data exec -i pg-1 -c postgres -- psql -U postgres -d foodbudget ... )

\set ON_ERROR_STOP on

-- ============================================================================
-- 1단계 — 롤 생성 (NOLOGIN) · 무해 · 앱 동작 불변
-- ============================================================================
-- 앱 서비스 11종 + 파이프라인 1종. `mp-operations` 는 **우리 PG 를 안 쓴다**(외부 교육용 DB —
-- config 레포 services/operations/base/externalsecret.yaml 주석) → 롤 없음.
-- `mp-frontend` 는 nginx 라 DB 를 안 쓴다 → 롤 없음.

DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY[
    -- 그룹 롤(로그인 불가 · 권한 묶음)
    'mp_data_reader',        -- public(데이터 티어) 읽기
    'mp_data_writer',        -- public 쓰기 (= reader + DML)
    -- 서비스 롤
    'svc_account', 'svc_recipebook', 'svc_pantry', 'svc_mealplan', 'svc_price',
    'svc_notify', 'svc_chat', 'svc_recipe', 'svc_video', 'svc_ocr', 'svc_ranking',
    'svc_pipeline',
    -- 🔴 CDC 롤 — 2026-08-14 추가. **서비스 롤이 아니라 PGSync(PG→ES) 전용**이다.
    --    이 파일이 `pgsync` 를 몰랐던 탓에 **빈 클러스터에 이 파일을 돌려도 PGSync 가 못 붙었다**
    --    (EKS A1 실측: `password authentication failed for user "pgsync"`).
    --    온프렘엔 손으로 만든 롤이 이미 있어서 드러나지 않았을 뿐이고, 같은 구멍이
    --    **온프렘 DR 재구축에도 있었다.** 아래 `IF NOT EXISTS` 라 온프렘 재실행은 무해하다.
    'pgsync'
  ] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', r);
      RAISE NOTICE 'created role %', r;
    END IF;
  END LOOP;
END $$;

-- ============================================================================
-- 2단계 — 그룹 롤 권한
-- ============================================================================
-- public = 데이터 티어(크롤 + 공공데이터). schema-production.md §0.5 의 `data` 범위와 같은 것.

-- ── mp_data_reader : 읽기 ────────────────────────────────────────────────────
GRANT USAGE ON SCHEMA public TO mp_data_reader;
GRANT SELECT ON ALL TABLES    IN SCHEMA public TO mp_data_reader;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO mp_data_reader;
-- 🔴 매터리얼라이즈드 뷰는 명시 GRANT — `ALL TABLES` 포함 여부가 버전 문서상 모호해 못 박는다.
GRANT SELECT ON public.retail_unit_price TO mp_data_reader;

-- 앞으로 만들어질 public 객체까지 자동 반영. ALTER DEFAULT PRIVILEGES 는 **생성 롤 단위**라
-- 현재 소유자(fbapp)와 3단계 전환 후 소유자(svc_pipeline) 둘 다 걸어둔다.
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp        IN SCHEMA public GRANT SELECT ON TABLES    TO mp_data_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp        IN SCHEMA public GRANT SELECT ON SEQUENCES TO mp_data_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE svc_pipeline IN SCHEMA public GRANT SELECT ON TABLES    TO mp_data_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE svc_pipeline IN SCHEMA public GRANT SELECT ON SEQUENCES TO mp_data_reader;

-- ── mp_data_writer : 쓰기 (파이프라인 전용) ──────────────────────────────────
GRANT mp_data_reader TO mp_data_writer;
GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mp_data_writer;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO mp_data_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp        IN SCHEMA public GRANT INSERT, UPDATE, DELETE ON TABLES TO mp_data_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp        IN SCHEMA public GRANT USAGE ON SEQUENCES TO mp_data_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE svc_pipeline IN SCHEMA public GRANT INSERT, UPDATE, DELETE ON TABLES TO mp_data_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE svc_pipeline IN SCHEMA public GRANT USAGE ON SEQUENCES TO mp_data_writer;

-- ============================================================================
-- 3단계 — 서비스별 자기 스키마 권한
-- ============================================================================
-- 원칙 3가지:
--  ① CREATE 는 주지 않는다. schema-production.md §0.3 초안은 `USAGE, CREATE` 였지만,
--     DDL 은 schema-production.sql 을 **사람이 fbapp/postgres 로** 돌리는 경로 하나만 남긴다.
--     서비스 코드에 DDL 이 하나도 없음을 실측했다(services/**/*.py 에 CREATE/ALTER/TRUNCATE 0건).
--  ② 남의 스키마에는 GRANT 를 안 한다 → PostgreSQL 기본 거부로 크로스서비스가 자동 차단된다.
--  ③ 소유권은 전부 fbapp 에 남긴다. 소유권 이관은 되돌리기가 비싸고 이 이슈의 목표가 아니다.

-- ── account ──────────────────────────────────────────────────────────────────
GRANT USAGE ON SCHEMA account TO svc_account;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA account TO svc_account;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA account TO svc_account;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp IN SCHEMA account GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO svc_account;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp IN SCHEMA account GRANT USAGE, SELECT                  ON SEQUENCES TO svc_account;
-- account 는 데이터 티어를 안 읽는다(§0.3 과 일치 · 코드 실측도 0건).

-- ── recipebook ───────────────────────────────────────────────────────────────
GRANT USAGE ON SCHEMA recipebook TO svc_recipebook;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA recipebook TO svc_recipebook;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA recipebook TO svc_recipebook;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp IN SCHEMA recipebook GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO svc_recipebook;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp IN SCHEMA recipebook GRANT USAGE, SELECT                  ON SEQUENCES TO svc_recipebook;
GRANT mp_data_reader TO svc_recipebook;   -- public.recipe · item_master · item_alias · retail_item_price_compare · food_nutrition

-- ── pantry ───────────────────────────────────────────────────────────────────
GRANT USAGE ON SCHEMA pantry TO svc_pantry;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA pantry TO svc_pantry;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA pantry TO svc_pantry;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp IN SCHEMA pantry GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO svc_pantry;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp IN SCHEMA pantry GRANT USAGE, SELECT                  ON SEQUENCES TO svc_pantry;
-- 🔴 §0.3 은 pantry 에 data 읽기(shelf_life_ref 소비기한 조인)를 준다. 그러나 **현재 pantry
--    서비스 코드에 public 테이블 SQL 이 0건**이다(소비기한 계산은 pipeline 의
--    recompute_pantry_expire.py 가 한다) → 최소권한으로 안 준다.
--    소비기한 계산이 서비스로 들어오면 아래 한 줄을 살린다:
-- GRANT mp_data_reader TO svc_pantry;

-- ── mealplan ─────────────────────────────────────────────────────────────────
GRANT USAGE ON SCHEMA mealplan TO svc_mealplan;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA mealplan TO svc_mealplan;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA mealplan TO svc_mealplan;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp IN SCHEMA mealplan GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO svc_mealplan;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp IN SCHEMA mealplan GRANT USAGE, SELECT                  ON SEQUENCES TO svc_mealplan;
GRANT mp_data_reader TO svc_mealplan;     -- public.recipe · recipe_ingredient · retail_item_price_compare · item_master
-- 🔴 크로스-스키마 쓰기 **2건** — mealplan 이 activity 에 **직접 INSERT** 한다.
--    ① 추천 노출  services/mealplan/app/queries.py insert_impressions
--    ② 클릭스트림 동 insert_user_event (C-88 · EVENT_SINK=pg — AWS 엔 Kafka 가 없다 · C-44)
--    테이블 2개 · INSERT 만으로 못 박는다(UPDATE·DELETE·SELECT 없음).
--
-- ⟳ 🔴 **정정(2026-08-14 실측) — 종전 주석 "시퀀스 불요(impression_id 는 앱이 만든 uuid)" 는 틀렸다.**
--    uuid 인 것은 `impression_id`(멱등키)이고 **PK `id` 는 `bigserial`** 이다. INSERT 문이 `id` 를
--    넣지 않으므로 기본값 `nextval()` 이 돌고, 그건 **시퀀스 USAGE 를 요구한다**
--    (`bigserial` 은 IDENTITY 가 아니라 소유된 시퀀스라 권한이 따로 필요하다).
--
--    실측(EKS PG):
--        activity.recipe_impression        INSERT = t
--        activity.recipe_impression_id_seq USAGE  = f    ← 여기서 막힌다
--
--    🟡 **지금 당장 깨져 있지는 않다** — `IMPRESSION_LOG_ENABLED` 가 base 에서 `"false"` 라
--       `insert_impressions` 가 호출되지 않는다(`routers.py:218`). ⇒ **잠재 지뢰다.**
--    🔴 그런데 그 지뢰가 나쁜 종류다: 플래그를 `true` 로 올리는 순간 INSERT 가 실패하고,
--       `except Exception: return 0` 으로 감싼 best-effort 라 **에러 없이 0건**을 돌려준다.
--       추천은 멀쩡히 나가므로 아무도 눈치채지 못한 채 랭커 학습 라벨만 안 쌓인다.
--       ⇒ *"플래그를 켰는데 왜 데이터가 없지"* 로 발견될 때까지의 데이터는 되돌릴 수 없다.
--    ⇒ 아래 시퀀스 GRANT 2줄 중 첫 줄은 ②의 부속이 아니라 **①을 켤 수 있게 만드는 선행**이다.
GRANT USAGE  ON SCHEMA activity TO svc_mealplan;
GRANT INSERT ON activity.recipe_impression TO svc_mealplan;
GRANT USAGE  ON SEQUENCE activity.recipe_impression_id_seq TO svc_mealplan;
GRANT INSERT ON activity.user_event TO svc_mealplan;
GRANT USAGE  ON SEQUENCE activity.user_event_id_seq TO svc_mealplan;

-- ── price ────────────────────────────────────────────────────────────────────
GRANT USAGE ON SCHEMA price TO svc_price;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA price TO svc_price;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA price TO svc_price;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp IN SCHEMA price GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO svc_price;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp IN SCHEMA price GRANT USAGE, SELECT                  ON SEQUENCES TO svc_price;
GRANT mp_data_reader TO svc_price;        -- item_master · item_alias · price_item · price_online_daily · retail_*

-- ── notify ───────────────────────────────────────────────────────────────────
GRANT USAGE ON SCHEMA notify TO svc_notify;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA notify TO svc_notify;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA notify TO svc_notify;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp IN SCHEMA notify GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO svc_notify;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp IN SCHEMA notify GRANT USAGE, SELECT                  ON SEQUENCES TO svc_notify;
-- notify 는 데이터 티어를 안 읽는다(생성 서비스가 title/body 를 완성해 넘긴다 — §0.3 과 일치).

-- ── chat ─────────────────────────────────────────────────────────────────────
GRANT USAGE ON SCHEMA chat TO svc_chat;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA chat TO svc_chat;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA chat TO svc_chat;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp IN SCHEMA chat GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO svc_chat;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp IN SCHEMA chat GRANT USAGE, SELECT                  ON SEQUENCES TO svc_chat;
GRANT mp_data_reader TO svc_chat;         -- item_master · item_unit_weight · recipe · recipe_ingredient · retail_* · food_nutrition
-- ⭐ 이 줄이 이슈 #546 의 핵심이다 — 전환 뒤 chat 은 account.app_user 를 **못 읽는다**.
--    (챗봇 제외재료 연동은 이미 account HTTP API 경유다 — services/chat/app/pipeline/account_client.py)

-- ── recipe (읽기 전용 서비스) ────────────────────────────────────────────────
GRANT mp_data_reader TO svc_recipe;
-- 자기 스키마 없음. recipe · recipe_ingredient · recipe_step · recipe_review_summary ·
-- food_nutrition · item_master · item_unit_weight · retail_* 만 SELECT.

-- ── video (읽기 전용) ────────────────────────────────────────────────────────
GRANT mp_data_reader TO svc_video;        -- item_master · item_unit_weight · recipe_ingredient · food_nutrition · retail_unit_price

-- ── ocr (읽기 전용 · Pooler 우회) ────────────────────────────────────────────
GRANT mp_data_reader TO svc_ocr;          -- item_master · item_alias · shelf_life_ref
-- ⚠️ ocr 은 `conn.read_only = True` 세션 가드를 쓴다(config 레포 pg-direct.yaml).
--    이제 롤 자체가 읽기 전용이라 **DB 가 두 번째 방어선**이 된다.

-- ── ranking-serving (읽기 전용 · Pooler 우회) ────────────────────────────────
GRANT mp_data_reader TO svc_ranking;      -- public.recipe_ingredient
GRANT USAGE  ON SCHEMA activity TO svc_ranking;
GRANT SELECT ON activity.user_event, activity.recipe_popularity, activity.user_chat_pref TO svc_ranking;

-- ── pgsync (CDC · PG→ES) ─────────────────────────────────────────────────────
-- 🔴 **서비스 롤이 아니다.** PGSync 가 논리 복제로 PG 를 읽어 ES 로 옮긴다
--    (동기화 범위 = `public.recipe` 계열 + `recipebook.shared_recipe`).
-- 🔴 `TRIGGER` 가 필요한 이유 = PGSync 가 대상 테이블에 **자기 트리거를 만든다.**
--    SELECT 만 주면 부팅은 되고 **동기화만 조용히 안 된다** — 가장 나쁜 실패 모양이다.
-- 🔴 `REPLICATION` 속성은 여기가 아니라 **CNPG `managed.roles`** 가 준다(§4.1 의 역할 분담).
--    이 파일은 LOGIN·비밀번호·복제속성을 건드리지 않는다.
-- 🟢 아래는 온프렘 실물에서 뜬 권한 그대로다(2026-08-14 `information_schema.table_privileges`)
--    — 온프렘에 다시 돌려도 같은 상태라 무해하다.
-- 🔴 **`CREATE` 가 필요하다 — `USAGE` 만으로는 부팅이 안 된다.** PGSync 의 `bootstrap` 이
--    `public.table_notify()` 트리거 함수를 **직접 만든다**(온프렘 실물도 그 함수의 owner 가 `pgsync`).
--    없으면 `permission denied for schema public` 로 bootstrap 이 죽고 복제 슬롯이 안 생긴다.
--    ⚠️ 2026-08-14 최초 커밋에서 `USAGE` 만 줬다가 EKS 실측으로 잡았다 — **권한을 뜰 때
--      `information_schema.table_privileges`(테이블)만 보면 스키마 ACL 을 놓친다.**
--      스키마 권한은 `pg_namespace.nspacl` 로 따로 떠야 한다(온프렘 = `pgsync=UC`).
GRANT USAGE, CREATE ON SCHEMA public, recipebook TO pgsync;
GRANT SELECT, TRIGGER ON public.recipe, public.recipe_ingredient TO pgsync;
GRANT SELECT, TRIGGER ON recipebook.shared_recipe TO pgsync;

-- ============================================================================
-- 4단계 — 파이프라인 롤 (별건 · 앱 전환이 끝난 뒤에 적용)
-- ============================================================================
-- 파이프라인은 데이터 티어의 **생산자**다. 실측 접근 대상:
--   public.*                       (크롤·공공데이터 적재 전부 — CRUD)
--   activity.*                     (consume_user_event · chat-insights · prune_user_data)
--   notify.notification            (consume_price_anomaly — INSERT)
--   pantry.pantry_item             (recompute_pantry_expire — UPDATE)
--   chat.chat_message              (prune_user_data — DELETE, 보존창·동의철회 청소)
--   account.app_user               (prune_user_data — SELECT, 동의철회 유저 조회)
GRANT mp_data_writer TO svc_pipeline;

GRANT USAGE ON SCHEMA activity TO svc_pipeline;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA activity TO svc_pipeline;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA activity TO svc_pipeline;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp IN SCHEMA activity GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO svc_pipeline;
ALTER DEFAULT PRIVILEGES FOR ROLE fbapp IN SCHEMA activity GRANT USAGE, SELECT                  ON SEQUENCES TO svc_pipeline;

GRANT USAGE          ON SCHEMA notify TO svc_pipeline;
GRANT SELECT, INSERT ON notify.notification TO svc_pipeline;
GRANT USAGE, SELECT  ON ALL SEQUENCES IN SCHEMA notify TO svc_pipeline;

GRANT USAGE          ON SCHEMA pantry TO svc_pipeline;
GRANT SELECT, UPDATE ON pantry.pantry_item TO svc_pipeline;
-- ⚠️ pantry.pantry_expire_backfill_log 는 **일회성 마이그레이션 SQL 만** 쓴다
--    (docs/prd/migrations/2026-07-29g_pantry_expire_backfill.sql). 파이프라인 코드에 참조 0건 → 미부여.

-- 🔴 chat · account — `mp-user-data-pruner`(prune_user_data.py) 하나 때문에 필요하다.
--    ① 보존창(180일) 지난 chat.chat_message 삭제
--    ② 동의 철회 유저(`account.app_user.activity_consent is false`) 잔여 데이터 청소
--    이 잡이 account 를 **읽어야** 하므로 파이프라인을 account 에서 완전히 떼어낼 수는 없다.
--    대신 **컬럼 단위 GRANT** 로 좁힌다 — email·password_hash 는 못 읽는다.
GRANT USAGE  ON SCHEMA chat TO svc_pipeline;
GRANT SELECT, DELETE ON chat.chat_message TO svc_pipeline;

GRANT USAGE  ON SCHEMA account TO svc_pipeline;
GRANT SELECT (id, activity_consent) ON account.app_user TO svc_pipeline;
--   검증: SELECT has_column_privilege('svc_pipeline','account.app_user','password_hash','SELECT'); -- 기대 f
--         SELECT has_column_privilege('svc_pipeline','account.app_user','activity_consent','SELECT'); -- 기대 t

-- 🔴 REFRESH MATERIALIZED VIEW 는 GRANT 로 못 준다 — **소유자만** 할 수 있다.
--    mp-poller-price-matview 가 public.retail_unit_price 를 갱신하므로 이 객체 하나만 넘긴다.
--    되돌리기 = `ALTER MATERIALIZED VIEW public.retail_unit_price OWNER TO fbapp;`
--    ⚠️ 이 줄만 유일하게 소유권을 바꾼다. 4단계 적용 전까지는 주석으로 둔다.
-- ALTER MATERIALIZED VIEW public.retail_unit_price OWNER TO svc_pipeline;

-- ⚠️ 파이프라인은 DDL 을 **자동으로 돌리지 않는다** — migrate_*.py / apply_schema.py 는
--    CronJob 이 아니라 사람이 돌리는 일회성 스크립트다(실측: CronJob 17개 args 전수 확인).
--    그래서 svc_pipeline 에 CREATE·ALTER 권한을 주지 않는다. 마이그레이션은 계속 fbapp/postgres 로.

-- ============================================================================
-- 5단계 — fbapp 회수 (전 서비스 전환 검증 후 · 별도 승인)
-- ============================================================================
-- fbapp 은 **객체 소유자로 남긴다**(소유권 이관 없음). 로그인 경로만 닫는다.
-- 되돌리기 = `ALTER ROLE fbapp LOGIN;` (비밀번호는 그대로 남아 있다)
-- ALTER ROLE fbapp NOLOGIN;
--
-- 선택 하드닝 — DB 접속 자체를 화이트리스트로. 🔴 CONNECT 를 PUBLIC 에서 뺄 거면
-- 아래 GRANT 를 **같은 트랜잭션에서** 반드시 함께 돌려야 한다. 하나라도 빠지면 그 워크로드가 죽는다.
-- BEGIN;
--   GRANT CONNECT ON DATABASE foodbudget TO
--     fbapp, pgsync, cnpg_metrics_exporter,
--     svc_account, svc_recipebook, svc_pantry, svc_mealplan, svc_price,
--     svc_notify, svc_chat, svc_recipe, svc_video, svc_ocr, svc_ranking, svc_pipeline;
--   REVOKE CONNECT ON DATABASE foodbudget FROM PUBLIC;
-- COMMIT;

-- ============================================================================
-- 검증 쿼리 (읽기 전용 · 적용 후 그대로 붙여넣어 확인)
-- ============================================================================
-- ① 롤이 다 생겼나
--   SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname LIKE 'svc\_%' OR rolname LIKE 'mp\_data%' ORDER BY 1;
-- ② 각 롤이 실제로 무엇을 볼 수 있나 (핵심 회귀 — chat 이 account 를 못 봐야 한다)
--   SELECT has_table_privilege('svc_chat','account.app_user','SELECT');       -- 기대 f
--   SELECT has_table_privilege('svc_chat','chat.chat_message','INSERT');      -- 기대 t
--   SELECT has_table_privilege('svc_chat','public.item_master','SELECT');     -- 기대 t
--   SELECT has_table_privilege('svc_recipe','public.recipe','INSERT');        -- 기대 f
--   SELECT has_table_privilege('svc_mealplan','activity.recipe_impression','INSERT');  -- 기대 t
--   SELECT has_table_privilege('svc_mealplan','activity.user_event','SELECT');         -- 기대 f
-- ③ 전수 매트릭스 (스키마 × 롤)
--   SELECT r.rolname, n.nspname,
--          count(*) FILTER (WHERE has_table_privilege(r.rolname, c.oid, 'SELECT')) AS sel,
--          count(*) FILTER (WHERE has_table_privilege(r.rolname, c.oid, 'INSERT')) AS ins
--     FROM pg_roles r
--     CROSS JOIN pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
--    WHERE r.rolname LIKE 'svc\_%' AND c.relkind IN ('r','p','v','m')
--      AND n.nspname NOT IN ('pg_catalog','information_schema')
--    GROUP BY 1,2 HAVING count(*) FILTER (WHERE has_table_privilege(r.rolname, c.oid, 'SELECT')) > 0
--    ORDER BY 1,2;
