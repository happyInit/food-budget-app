-- 두 PG 클러스터의 **내용** 동일성 판정 (A3 컷오버 게이트 · DR 검증 겸용)
--
-- 사용:
--   psql -U postgres -d foodbudget -At -f verify-parity.sql | sort > a.txt   (온프렘)
--   psql -U postgres -d foodbudget -At -f verify-parity.sql | sort > b.txt   (EKS)
--   join -j1 <(sed 's/ /|/' a.txt) <(sed 's/ /|/' b.txt) -t'|' -o 0,1.2,2.2 \
--     | awk -F'|' '$2!=$3 {print; d++} END {print "불일치", d+0}'
--
-- 비용 실측(2026-08-14 · 41테이블 / 92만행): EKS 2.7초 · 온프렘 4.5초.
--
-- ── 🔴 왜 `t::text` 가 아니라 `to_jsonb(t)` 인가 ─────────────────────────────
-- 행을 `t::text` 로 찍으면 **컬럼 순서까지 해시에 들어간다.** 온프렘과 EKS 는
-- 물리 컬럼 순서가 다르다 — 온프렘은 `docs/prd/migrations/*.sql` 의
-- `ALTER TABLE ADD COLUMN` 이 컬럼을 **뒤에 붙인** 결과이고, EKS 는
-- `schema-production.sql` 의 **선언 순서**를 그대로 받았기 때문이다.
-- 실측(2026-08-14) 차이 5개 테이블:
--     food_nutrition · recipe_review_summary · retail_price
--     shelf_life_ref · recipebook.user_recipe
-- 이건 **무해하다** — PostgreSQL 은 순서로 의미를 두지 않고, 앱은 이름으로 읽으며
-- (`row_factory=dict_row`), `pg_dump -Fc --data-only` 의 COPY 도 컬럼명을 명시하므로
-- 복원이 **위치가 아니라 이름으로 매핑**된다(그래서 복원은 멀쩡했다).
-- 🔴 그런데 `t::text` 체크섬은 이걸 **데이터 불일치로 오탐한다.** 실제로 첫 판정에서
--    6/41 불일치가 나왔고 그중 5건이 순서였다. `to_jsonb` 는 키 순서를 정규화하므로
--    순서에 둔감하다 — 그걸로 다시 재니 불일치가 **1건**(의도적 제외분)으로 줄었다.
--
-- ── 정렬을 왜 해시로 하나 ────────────────────────────────────────────────────
-- `order by h` = 행 해시 자체로 정렬한다. PK 이름을 몰라도 되고, PK 가 없는 표에서도
-- 결정적이며, 물리 순서(clustering·vacuum)에 영향받지 않는다.
--
-- ── 읽는 법 ─────────────────────────────────────────────────────────────────
--   · `public.crawl_raw` 불일치는 **정상**이다 — A3 는 이 표를 일부러 제외한다
--     (소비자가 전부 `pipelines/` 이고 앱 12종엔 0건 · FK 양방향 0건 · 186MB).
--   · 그 외 불일치가 하나라도 있으면 **컷오버 전에 원인을 밝힌다.**
--   · 표 개수 자체가 다르면 스키마가 어긋난 것이다 →
--     `docs/prd/migrations/2026-08-14_eks_schema_catchup.sql` 참조.

select table_schema||'.'||table_name||' '||
  (xpath('/row/h/text()', query_to_xml(
     format('select coalesce(md5(string_agg(h, '''' order by h)), ''EMPTY'') as h '
            'from (select md5(to_jsonb(t)::text) h from %I.%I t) s',
            table_schema, table_name), false, true, '')))[1]::text
from information_schema.tables
where table_type = 'BASE TABLE'
  and table_schema not in ('pg_catalog', 'information_schema')
order by 1;
