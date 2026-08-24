#!/usr/bin/env bash
# 두 클러스터 PG 의 **스키마**(인덱스·컬럼·제약)를 대조하고, 필요하면 멱등 DDL 을 적용한다.
#
# ── 🔴 왜 필요한가 (2026-08-24 실제 사고) ─────────────────────────────────────
# `mealplan.ux_cart_item_user_item`(#614 의 부분 유니크)이 **EKS 에만 없었다.**
#   · 코드는 `ON CONFLICT (user_id, item_id) WHERE item_id IS NOT NULL` 로 그 인덱스를
#     arbiter 로 추론하는데, PostgreSQL 은 이 추론을 **계획 시점에 검증**한다
#     ⇒ 충돌 여부와 무관하게 **모든 INSERT 가 실패**했다(`InvalidColumnReference`).
#   · 원인 = #614 머지(2026-08-13)와 A1 데이터 이관(08-13~14)이 겹쳤다. EKS 는 인덱스가
#     추가되기 직전 형상으로 적재됐고, 이후 `schema-production.sql` 이 재적용된 적이 없다.
#   · 🔴 **`docs/prd/verify-parity.sql` 은 이걸 못 잡는다** — 41개 테이블의 «내용» 체크섬만
#     본다. 인덱스·제약은 검사 대상이 아니라 그대로 통과했다. 이 스크립트가 그 구멍이다.
#
# ── 사용법 ────────────────────────────────────────────────────────────────────
#   ./scripts/schema-parity.sh check              온프렘 ↔ EKS 스키마 대조 (기본)
#   ./scripts/schema-parity.sh apply eks          EKS 에 멱등 DDL 적용
#   ./scripts/schema-parity.sh apply onprem       온프렘에 멱등 DDL 적용
#
# 🔴 이 레포는 공개다 — 실주소·계정을 적지 않는다. 접속 방법은 환경변수로 주입한다.
#    기본값은 CLAUDE.md 가 정한 방식(EKS=kubectl 직결 / 온프렘=`ssh wsl-dev` 경유)이다.
#      EKS_KUBECTL="kubectl"
#      ONPREM_KUBECTL="ssh wsl-dev kubectl"
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DDL_DATA="$REPO/docs/prd/schema-public-data.sql"
DDL_APP="$REPO/docs/prd/schema-production.sql"

EKS_KUBECTL="${EKS_KUBECTL:-kubectl}"
ONPREM_KUBECTL="${ONPREM_KUBECTL:-ssh wsl-dev kubectl}"
PG_NS="${PG_NS:-data}"
PG_DB="${PG_DB:-foodbudget}"

say() { printf '\033[1;36m• %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
bad() { printf '\033[1;31m✗ %s\033[0m\n' "$*"; }
die() { bad "$*"; exit 1; }

# 대상별 kubectl 전문 + primary 파드 이름을 뱉는다.
kc_for() {
  case "$1" in
    eks)    echo "$EKS_KUBECTL" ;;
    onprem) echo "$ONPREM_KUBECTL" ;;
    *)      die "대상은 eks | onprem 이다 (받은 값: $1)" ;;
  esac
}

# 🔴 `</dev/null` 이 필수다 — 온프렘 경로는 ssh 를 타는데 **ssh 는 stdin 을 통째로 읽어
#    원격으로 보낸다.** 이 함수가 psql 파이프라인 «안에서» 불리면 뒤이어 실행될 psql 이
#    받아야 할 SQL 을 여기서 먹어치운다 ⇒ psql 은 빈 입력을 받고 **0행을 조용히 반환**한다.
#    (kubectl 직결인 EKS 는 stdin 을 안 읽어 멀쩡하다 — 그래서 «한쪽만 비어 보이는»
#     증상이 되고, DB 가 비었나 의심하게 된다. 2026-08-24 실제로 밟았다.)
_PRIMARY_CACHE_eks=""; _PRIMARY_CACHE_onprem=""
primary_of() {                      # CNPG 가 현재 primary 로 지목한 파드 (대상별 1회만 조회)
  local var="_PRIMARY_CACHE_$1" kc
  if [ -z "${!var}" ]; then
    kc="$(kc_for "$1")"
    printf -v "$var" '%s' \
      "$($kc -n "$PG_NS" get cluster pg -o jsonpath='{.status.currentPrimary}' 2>/dev/null </dev/null | tr -d '\r')"
  fi
  printf '%s' "${!var}"
}

psql_on() {                         # $1=대상, stdin=SQL → psql -tA 결과
  local kc pod; kc="$(kc_for "$1")"; pod="$(primary_of "$1")"
  [ -n "$pod" ] || die "$1: PG primary 파드를 못 찾았다 (접속 설정을 확인하라)"
  $kc -n "$PG_NS" exec -i "$pod" -c postgres -- psql -U postgres -d "$PG_DB" -tA -v ON_ERROR_STOP=1
}

# ── 스키마 지문 ───────────────────────────────────────────────────────────────
# 🔴 인덱스는 **이름이 아니라 정의**로 비교한다 — 같은 인덱스를 양쪽이 다른 이름으로
#    갖고 있는 경우가 실제로 5쌍 있었다(이름만 보면 10건이 어긋난 것처럼 보인다).
SQL_INDEX="select schemaname||'.'||tablename||' :: '||
  regexp_replace(indexdef,'^CREATE (UNIQUE )?INDEX \\S+ ON ','\\1ON ')
  from pg_indexes
  where schemaname not in ('pg_catalog','information_schema') order by 1;"

SQL_COLUMN="select table_schema||'.'||table_name||'.'||column_name||' '||data_type||
  coalesce(' default='||column_default,'')||case when is_nullable='NO' then ' NOT NULL' else '' end
  from information_schema.columns
  where table_schema not in ('pg_catalog','information_schema') order by 1;"

SQL_CONSTRAINT="select conrelid::regclass::text||' :: '||contype::text||' '||pg_get_constraintdef(c.oid)
  from pg_constraint c
  join pg_namespace n on n.oid=c.connamespace
  where n.nspname not in ('pg_catalog','information_schema') order by 1;"

diff_one() {                        # $1=제목  $2=SQL
  local title="$1" sql="$2" a b n
  a="$(mktemp)"; b="$(mktemp)"
  printf '%s' "$sql" | psql_on onprem | sed 's/[[:space:]]*$//' | sort > "$a"
  printf '%s' "$sql" | psql_on eks    | sed 's/[[:space:]]*$//' | sort > "$b"
  printf '\n\033[1m── %s\033[0m  (온프렘 %s · EKS %s)\n' \
    "$title" "$(wc -l < "$a")" "$(wc -l < "$b")"
  n=0
  while IFS= read -r line; do bad "온프렘에만: $line"; n=$((n+1)); done < <(comm -23 "$a" "$b")
  while IFS= read -r line; do bad "EKS에만  : $line"; n=$((n+1)); done < <(comm -13 "$a" "$b")
  [ "$n" -eq 0 ] && ok "일치"
  rm -f "$a" "$b"
  return "$n"
}

cmd_check() {
  local rc=0
  diff_one "인덱스 (정의 기준)" "$SQL_INDEX"      || rc=$((rc+$?))
  diff_one "컬럼"               "$SQL_COLUMN"     || rc=$((rc+$?))
  diff_one "제약"               "$SQL_CONSTRAINT" || rc=$((rc+$?))
  echo
  if [ "$rc" -eq 0 ]; then ok "스키마 동일 — 어긋남 0건"; else
    bad "어긋남 $rc 건 — \`apply\` 로 멱등 DDL 을 적용하거나 의도된 차이인지 판단하라"
  fi
  return "$rc"
}

cmd_apply() {
  local target="${1:-}"
  [ -n "$target" ] || die "대상을 지정하라: apply eks | apply onprem"
  [ -f "$DDL_DATA" ] && [ -f "$DDL_APP" ] || die "DDL 파일을 못 찾았다 ($DDL_DATA / $DDL_APP)"
  # 🔴 순서 고정 — 데이터 티어(item_master 등)가 먼저 있어야 앱 스키마의 FK 가 붙는다.
  for f in "$DDL_DATA" "$DDL_APP"; do
    say "$target ← $(basename "$f")"
    psql_on "$target" < "$f"
  done
  ok "적용 완료 (멱등 — 재실행해도 안전하다)"
}

case "${1:-check}" in
  check) cmd_check ;;
  apply) shift; cmd_apply "$@" ;;
  *)     die "사용법: $0 [check | apply <eks|onprem>]" ;;
esac
