#!/usr/bin/env bash
# dev-db.sh — fb-data(192.168.0.8)의 공유 PostgreSQL(컨테이너 tfstate-db)에
#   격리된 로컬 개발용 DB를 생성 / 스키마적용 / 삭제한다.
#   WSL에서 실행 → SSH로 0.8 접속 → docker exec 로 컨테이너 안에서 psql.
#   기존 앱 DB 생성 방식(infra/ansible/roles/tfstate_db) 그대로 미러링.
# ⚠️ 로컬 개발 편의용 — infra SoT 아님. git 에 커밋하지 말 것.
set -euo pipefail

# ── 설정 (환경변수로 덮어쓰기 가능:  DB=foo ./dev-db.sh up) ─────────────────
SSH_HOST="${SSH_HOST:-ubuntu@192.168.0.8}"    # fb-data VM
PG_CT="${PG_CT:-tfstate-db}"                   # PostgreSQL 컨테이너명
SUPER="${SUPER:-terraform}"                    # 부트스트랩 슈퍼유저 (DB 생성 권한)
APP_ROLE="${APP_ROLE:-fbapp}"                  # 앱 롤 = 스키마 소유자
DB="${DB:-foodbudget_dev_team6}"               # 만들 dev DB 이름
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DDL_DATA="$REPO/docs/prd/schema-public-data.sql"   # 데이터 티어 (먼저 적용)
DDL_APP="$REPO/docs/prd/schema-production.sql"     # 서비스 스키마 + FK (다음)

say() { printf '\033[1;36m• %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

db_exists() {
  local out
  out="$(ssh "$SSH_HOST" "docker exec $PG_CT psql -U $SUPER -d postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='$DB'\"" 2>/dev/null | tr -d '[:space:]')" || true
  [ "$out" = "1" ]
}

apply() {  # $1 = 로컬 SQL 파일 → fbapp 로 스트리밍 (SSH stdin → docker exec -i → psql)
  say "$(basename "$1") 적용…"
  ssh "$SSH_HOST" "docker exec -i $PG_CT psql -U $APP_ROLE -d $DB -v ON_ERROR_STOP=1" < "$1"
}

cmd_up() {
  [ -f "$DDL_DATA" ] && [ -f "$DDL_APP" ] || die "DDL 파일 없음: $DDL_DATA / $DDL_APP"
  if db_exists; then
    say "DB '$DB' 이미 존재 → 생성/스키마 건너뜀 (다시 깔려면:  $0 recreate)"
  else
    say "DB '$DB' 생성 (소유자 $APP_ROLE)…"
    ssh "$SSH_HOST" "docker exec $PG_CT psql -U $SUPER -d postgres -c \"CREATE DATABASE $DB OWNER $APP_ROLE\""
    apply "$DDL_DATA"   # public-data 먼저 (recipe·item_master…)
    apply "$DDL_APP"    # production 다음 (서비스 스키마 + FK)
  fi
  cmd_status
  ok "준비 완료 — 서비스 .env 에  PGDATABASE=$DB  로 지정하세요 (PGHOST=192.168.0.8·PGUSER=$APP_ROLE·PGPASSWORD=<앱DB비번>)."
}

cmd_status() {
  say "'$DB' 스키마별 테이블 수:"
  ssh "$SSH_HOST" "docker exec $PG_CT psql -U $SUPER -d $DB -tAc \"SELECT table_schema||' : '||count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema') GROUP BY table_schema ORDER BY table_schema\"" || say "(DB '$DB' 아직 없음)"
}

cmd_drop() {
  say "DB '$DB' 삭제 (활성 연결 종료 후)…"
  ssh "$SSH_HOST" "docker exec $PG_CT psql -U $SUPER -d postgres -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB' AND pid<>pg_backend_pid()\"" >/dev/null 2>&1 || true
  ssh "$SSH_HOST" "docker exec $PG_CT psql -U $SUPER -d postgres -c \"DROP DATABASE IF EXISTS $DB\""
  ok "삭제됨."
}

cmd_psql() { ssh -t "$SSH_HOST" "docker exec -it $PG_CT psql -U $APP_ROLE -d $DB"; }

cmd_seed() {  # 데이터 티어(public: recipe·item_master·retail_*·food_nutrition…)를 실 foodbudget 에서 복사
  say "데이터 티어(public) 복사:  foodbudget → $DB"
  say "  (읽기전용 티어라 프로덕션 무변경 · account 등 OLTP/유저 데이터는 복사 안 함)"
  ssh "$SSH_HOST" "docker exec $PG_CT sh -c 'pg_dump -U $SUPER -d foodbudget --data-only --disable-triggers --schema=public | psql -U $SUPER -d $DB -v ON_ERROR_STOP=1 --single-transaction -q'"
  ok "복사 완료 — 이제 레시피·가격·핫딜·레시피북도 로컬에서 실데이터로 확인됩니다."
}

cmd_clone() {  # 데이터 티어를 prod 실구조+실데이터로 통째 복제 (repo DDL 드리프트 회피). 서비스 스키마는 repo DDL(빈 상태).
  say "dev DB '$DB' 재생성(기존 있으면 삭제 — 서비스 먼저 내려두세요)…"
  ssh "$SSH_HOST" "docker exec $PG_CT psql -U $SUPER -d postgres -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB' AND pid<>pg_backend_pid()\"" >/dev/null 2>&1 || true
  ssh "$SSH_HOST" "docker exec $PG_CT psql -U $SUPER -d postgres -c \"DROP DATABASE IF EXISTS $DB\""
  ssh "$SSH_HOST" "docker exec $PG_CT psql -U $SUPER -d postgres -c \"CREATE DATABASE $DB OWNER $APP_ROLE\""
  # prod dump 가 CREATE SCHEMA public 을 포함(PG15+) → dev 의 기본 public 을 먼저 제거해 충돌 회피
  ssh "$SSH_HOST" "docker exec $PG_CT psql -U $SUPER -d $DB -c \"DROP SCHEMA IF EXISTS public CASCADE\""
  say "데이터 티어(public) — prod 실구조+실데이터 복제…"
  ssh "$SSH_HOST" "docker exec $PG_CT sh -c 'pg_dump -U $SUPER -d foodbudget --schema=public --no-owner --no-privileges | psql -U $APP_ROLE -d $DB -v ON_ERROR_STOP=1 --single-transaction -q'"
  say "서비스 스키마(account·pantry·…) + FK — repo DDL 적용(빈 상태)…"
  ssh "$SSH_HOST" "docker exec -i $PG_CT psql -U $APP_ROLE -d $DB -v ON_ERROR_STOP=1" < "$DDL_APP"
  ok "완료 — 데이터 티어=prod 실데이터 · 서비스 스키마=빈 상태(쓰기 격리)."
  cmd_status
}

case "${1:-up}" in
  up)       cmd_up ;;
  clone)    cmd_clone ;;
  seed)     cmd_seed ;;
  recreate) cmd_drop; cmd_up ;;
  drop)     cmd_drop ;;
  status)   cmd_status ;;
  psql)     cmd_psql ;;
  *) die "사용법: $0 {up|clone|seed|recreate|drop|status|psql}   (env override: DB, SSH_HOST, PG_CT, SUPER, APP_ROLE)" ;;
esac
