-- collation 손상 전수 검사 (런북 §9-1) — musl(VM) → glibc(CNPG) 물리 복제의 유일한 실질 위험.
-- 🔴 PG 는 이걸 경고해 주지 못한다: datcollversion 이 NULL 이라 불일치 감지 로직이 발동하지 않는다.
--    그래서 "안 깨졌겠지" 가 아니라 이 스크립트로 매번 확인한다.
--
-- 언제: ① promote 직후 REINDEX 전(피해 규모 파악) ② REINDEX 후(0 이 나와야 한다)
--       ③ 🔴 CNPG 이미지의 base(glibc) 가 바뀌는 상향을 할 때마다
--   kubectl -n data exec -i pg-1 -c postgres -- psql -U postgres -d foodbudget -f - < pg-amcheck.sql
--
-- 2026-07-29 리허설 실측: REINDEX 전 btree 103개 중 13개 손상(UNIQUE 5·PK 2 포함) → REINDEX 후 0개.
CREATE EXTENSION IF NOT EXISTS amcheck;
DO $$
DECLARE r record; bad int := 0; tot int := 0;
BEGIN
  FOR r IN SELECT c.oid AS ioid, c.relname AS iname, n.nspname AS sname
           FROM pg_class c
           JOIN pg_namespace n ON n.oid = c.relnamespace
           JOIN pg_am a ON a.oid = c.relam
           WHERE c.relkind = 'i' AND a.amname = 'btree'
             AND n.nspname NOT IN ('pg_catalog','information_schema','pg_toast')
             AND c.relpersistence = 'p'
           ORDER BY 3, 2
  LOOP
    tot := tot + 1;
    BEGIN
      PERFORM bt_index_check(index => r.ioid, heapallindexed => true);
    EXCEPTION WHEN OTHERS THEN
      bad := bad + 1;
      RAISE NOTICE 'BAD  %.%  ::  %', r.sname, r.iname, SQLERRM;
    END;
  END LOOP;
  RAISE NOTICE '=== btree 인덱스 %개 검사, 손상 %개 ===', tot, bad;
END $$;
