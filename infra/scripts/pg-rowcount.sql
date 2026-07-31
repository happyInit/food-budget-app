-- §5-① PG 행 수 전수 대조 — VM(.8) 과 K8s 양쪽에서 같은 쿼리를 돌려 diff 한다.
-- 🔴 테이블 수를 고정값으로 박지 말 것 — 물리 복제는 DDL 도 따라오므로 목록 자체가 늘 수 있다
--    (2026-07-29 리허설 중 pantry.pantry_expire_backfill_log 가 생겨 40→41).
--
--   VM :  ssh ubuntu@192.168.0.8 "docker exec -i tfstate-db psql -U terraform -d foodbudget -At -F'|'" < pg-rowcount.sql > vm.txt
--   K8s:  kubectl -n data exec -i pg-1 -c postgres -- psql -U postgres -d foodbudget -At -F'|' -f - < pg-rowcount.sql > k8s.txt
--   diff: join -t'|' vm.txt k8s.txt | awk -F'|' '$2!=$3'
--         (쓰기 봉인 후라면 출력이 비어야 정상 — 런북 §5-①)
SELECT table_schema || '.' || table_name AS t,
       (xpath('/row/cnt/text()',
              query_to_xml(format('select count(*) as cnt from %I.%I', table_schema, table_name),
                           false, true, '')))[1]::text::bigint AS n
FROM information_schema.tables
WHERE table_type = 'BASE TABLE'
  AND table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY 1;
