#!/usr/bin/env bash
# 밀플래닝 포트폴리오 스택 — 데이터 초기 적재 (최초 1회)
#
#   ./bootstrap.sh            # PG 복원 + ES 색인 생성·적재
#   ./bootstrap.sh es         # ES 만
#   ./bootstrap.sh pg         # PG 만
#
# 시드 데이터는 S3(mp-backup-ap2/portfolio-seed/)에서 받는다. 스택이 떠 있어야 한다.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a

SEED_S3="${SEED_S3:-s3://mp-backup-ap2/portfolio-seed/20260830}"
SEED_DIR="${SEED_DIR:-./seed}"
WHAT="${1:-all}"
C() { docker compose "$@"; }

fetch() {
  mkdir -p "$SEED_DIR"
  if [ -f "$SEED_DIR/.done" ]; then echo "· 시드 이미 내려받음"; return; fi
  echo "· S3 에서 시드 내려받는 중 …"
  aws s3 cp "$SEED_S3/" "$SEED_DIR/" --recursive --only-show-errors
  gunzip -f "$SEED_DIR"/*.gz 2>/dev/null || true
  touch "$SEED_DIR/.done"
}

restore_pg() {
  echo "== PostgreSQL 복원 =="
  local dump; dump=$(ls -t "$SEED_DIR"/foodbudget-*.dump | head -1)
  echo "· 덤프: $(basename "$dump") ($(du -h "$dump" | cut -f1))"
  # 이미 데이터가 있으면 멈춘다 — 실수로 덮어쓰는 사고를 막는다.
  local n
  n=$(C exec -T postgres psql -U "${PGUSER:-fbapp}" -d "${PGDATABASE:-foodbudget}" -tAc \
        "select count(*) from information_schema.tables where table_schema='public'" 2>/dev/null || echo 0)
  if [ "${n:-0}" -gt 0 ]; then
    echo "  🔴 public 스키마에 테이블이 이미 ${n}개 있다. 덮어쓰려면 먼저 비울 것:"
    echo "     docker compose exec postgres psql -U ${PGUSER:-fbapp} -d ${PGDATABASE:-foodbudget} -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'"
    return 1
  fi
  # 🔴 -j(병렬)는 stdin 입력에서 지원되지 않는다("parallel restore from standard input is not supported").
  #    30MB 짜리라 단일 프로세스로 충분하다.
  C exec -T postgres pg_restore -U "${PGUSER:-fbapp}" -d "${PGDATABASE:-foodbudget}" \
      --no-owner --no-acl --no-privileges < "$dump"
  echo "· 복원된 테이블: $(C exec -T postgres psql -U "${PGUSER:-fbapp}" -d "${PGDATABASE:-foodbudget}" -tAc \
      "select count(*) from information_schema.tables where table_schema='public'")"
}

# 🔴 중첩 함수(C → es)로 감싸면 인자 전달이 꼬여 docker 가 "-T" 를 자기 플래그로 읽고
#    "unknown shorthand flag: 'T'" 로 죽는 일이 있었다(2026-08-30 실측). 한 겹으로만 둔다.
es() { docker compose exec -T elasticsearch curl -sS -H 'Content-Type: application/json' "$@"; }

load_index() {
  local idx="$1" mapping="$2" docs="$3"
  echo "-- $idx"
  # 저장된 매핑을 그대로 쓴다. 🔴 동적 매핑에 맡기면 cooking_time 이 text 로 잡혀
  #    term 필터가 0건이 된다(과거 실제 사고). replicas 만 단일 노드에 맞춰 0으로 낮춘다.
  python3 - "$mapping" > /tmp/mp-idx.json <<'PY'
import json,sys
d=json.load(open(sys.argv[1])); k=list(d)[0]
s=d[k]['settings']['index']
out={"settings":{"number_of_shards":s.get("number_of_shards","1"),
                 "number_of_replicas":"0"},
     "mappings":d[k]['mappings']}
if 'analysis' in s: out['settings']['analysis']=s['analysis']
json.dump(out,sys.stdout,ensure_ascii=False)
PY
  es -XDELETE "localhost:9200/$idx" >/dev/null 2>&1 || true
  es -XPUT "localhost:9200/$idx" -d @- < /tmp/mp-idx.json | head -c 200; echo
  # NDJSON → _bulk (2000건씩)
  python3 - "$docs" "$idx" > /tmp/mp-bulk.ndjson <<'PY'
import json,sys
idx=sys.argv[2]
with open(sys.argv[1],encoding='utf-8') as f, open('/dev/stdout','w') as o:
    for line in f:
        d=json.loads(line)
        o.write(json.dumps({"index":{"_index":idx,"_id":d["_id"]}})+"\n")
        o.write(json.dumps(d["_source"],ensure_ascii=False)+"\n")
PY
  split -l 4000 /tmp/mp-bulk.ndjson /tmp/mp-bulk-part-
  for p in /tmp/mp-bulk-part-*; do
    es -XPOST "localhost:9200/_bulk" --data-binary @- < "$p" \
      | python3 -c "import json,sys;d=json.load(sys.stdin);print('  bulk errors:',d.get('errors'))"
  done
  rm -f /tmp/mp-bulk-part-* /tmp/mp-bulk.ndjson /tmp/mp-idx.json
  es -XPOST "localhost:9200/$idx/_refresh" >/dev/null
  echo "  적재: $(es "localhost:9200/$idx/_count" | python3 -c 'import json,sys;print(json.load(sys.stdin)["count"])') 건"
}

restore_es() {
  echo "== Elasticsearch 색인 =="
  load_index recipes_v2        "$SEED_DIR/es-mapping-recipes_v2.json"        "$SEED_DIR/es-docs-recipes_v2.ndjson"
  load_index user_recipes_live "$SEED_DIR/es-mapping-user_recipes_live.json" "$SEED_DIR/es-docs-user_recipes_live.ndjson"
  # 🔴 앱은 별칭 recipes_live 를 읽는다(ES_INDEX 기본값). 이게 없으면 레시피 검색이 전부 실패한다.
  #    그래서 만들고 끝내지 않고, 실제로 붙었는지 확인한 뒤 없으면 실패로 끝낸다.
  es -XPOST "localhost:9200/_aliases" -d '{"actions":[{"add":{"index":"recipes_v2","alias":"recipes_live"}}]}' | head -c 120; echo
  local a
  a=$(es 'localhost:9200/_cat/aliases/recipes_live?h=alias,index' | tr -d ' \r\n')
  [ -n "$a" ] || { echo "  🔴 별칭 recipes_live 생성 실패 — 검색이 동작하지 않는다"; return 1; }
  echo "· 별칭 확인: $a"
}

fetch
case "$WHAT" in
  pg)  restore_pg ;;
  es)  restore_es ;;
  all) restore_pg; restore_es ;;
  *)   echo "usage: $0 [all|pg|es]"; exit 2 ;;
esac
echo "완료."
