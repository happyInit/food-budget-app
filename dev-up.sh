#!/usr/bin/env bash
# dev-up.sh — 모든 백엔드(uvicorn) + 프론트(vite)를 로컬에서 한꺼번에 띄운다.
#   DB = fb-data(192.168.0.8)의 foodbudget_dev_team6 (dev-db.sh 로 먼저 생성).
#   ★ per-service .env 를 건드리지 않고 공통 접속정보를 "환경변수"로 주입한다.
#     (pydantic-settings 우선순위: 환경변수 > .env 파일 > 기본값 → 모든 서비스가 dev DB + 동일 JWT_SECRET)
#   브라우저: http://localhost:5173
# ⚠️ 로컬 개발용 — git 에 커밋하지 말 것.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGDIR="$REPO/.devlogs"; PIDFILE="$LOGDIR/pids"
mkdir -p "$LOGDIR"

# ── 띄울 서비스 (이름:포트) — 필요없는 건 앞에 # ──────────────────────────────
SERVICES=(
  account:8004
  pantry:8005
  recipebook:8006
  mealplan:8007
  notify:8008
  recipe:8001
  price:8002
  # chat:8003     # ES(recipes 인덱스)+Redis 필요 — 쓸 거면 주석 해제
)

# ── 공통 접속/인증 env (각 서비스 .env 를 덮어씀) ────────────────────────────
export PGHOST="${PGHOST:-192.168.0.8}"
export PGPORT="${PGPORT:-5432}"
export PGDATABASE="${PGDATABASE:-foodbudget_dev_team6}"
export PGUSER="${PGUSER:-fbapp}"
export JWT_SECRET="${JWT_SECRET:-dev-insecure-change-me}"
export JWT_ALG="${JWT_ALG:-HS256}"
export ESHOST="${ESHOST:-192.168.0.8}"
export ESPORT="${ESPORT:-9200}"

# PGPASSWORD: 이미 export 돼 있으면 그걸, 아니면 루트 .env 에서 읽음 (값은 출력하지 않음)
if [ -z "${PGPASSWORD:-}" ] && [ -f "$REPO/.env" ]; then
  PGPASSWORD="$(sed -n 's/^PGPASSWORD=//p' "$REPO/.env" | head -1)"
  PGPASSWORD="${PGPASSWORD%\"}"; PGPASSWORD="${PGPASSWORD#\"}"
  PGPASSWORD="${PGPASSWORD%\'}"; PGPASSWORD="${PGPASSWORD#\'}"
fi
export PGPASSWORD

# node(nvm) PATH 확보
if ! command -v node >/dev/null 2>&1; then
  NB="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | tail -1 || true)"
  [ -n "$NB" ] && export PATH="$NB:$PATH"
fi

say(){ printf '\033[1;36m• %s\033[0m\n' "$*"; }
ok(){  printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
die(){ printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

ensure_venv(){  # $1 = 서비스 디렉토리
  [ -x "$1/.venv/bin/uvicorn" ] && return 0
  say "$(basename "$1") venv 준비(최초 1회, 조금 걸림)…"
  python3 -m venv "$1/.venv"
  "$1/.venv/bin/pip" install -q -r "$1/requirements.txt"
}

stop_tracked(){
  [ -f "$PIDFILE" ] || return 0
  while IFS=: read -r pid name port; do
    [ -n "${pid:-}" ] && kill "$pid" 2>/dev/null && echo "  ✗ $name (pid $pid) 종료" || true
  done < "$PIDFILE"
  rm -f "$PIDFILE"
}

cmd_up(){
  [ -n "${PGPASSWORD:-}" ] || die "PGPASSWORD 없음 — 루트 .env 에 PGPASSWORD 넣거나  PGPASSWORD=... ./dev-up.sh"
  stop_tracked                       # 이미 떠 있으면 먼저 정리
  : > "$PIDFILE"
  say "백엔드 기동 (DB=$PGDATABASE @ $PGHOST:$PGPORT · user=$PGUSER)…"
  local entry svc port dir
  for entry in "${SERVICES[@]}"; do
    svc="${entry%%:*}"; port="${entry##*:}"; dir="$REPO/services/$svc"
    [ -d "$dir" ] || { echo "  · $svc 디렉토리 없음 → 건너뜀"; continue; }
    ensure_venv "$dir"
    ( cd "$dir" && PYTHONPATH=. exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$port" ) \
        > "$LOGDIR/$svc.log" 2>&1 &
    echo "$!:$svc:$port" >> "$PIDFILE"
    echo "  ✓ $svc → http://localhost:$port   (log: .devlogs/$svc.log)"
  done
  say "프론트(vite) 기동…"
  [ -d "$REPO/frontend/node_modules" ] || ( cd "$REPO/frontend" && npm install )
  ( cd "$REPO/frontend" && exec ./node_modules/.bin/vite ) > "$LOGDIR/frontend.log" 2>&1 &
  echo "$!:frontend:5173" >> "$PIDFILE"
  echo "  ✓ frontend → http://localhost:5173"
  say "부팅 대기…"; sleep 5
  cmd_status
  echo ""
  ok "브라우저에서 열기 →  http://localhost:5173"
  echo "   로그: ./dev-up.sh logs <svc>   ·   종료: ./dev-up.sh down"
}

cmd_status(){
  local entry svc port code
  say "헬스 체크:"
  for entry in "${SERVICES[@]}"; do
    svc="${entry%%:*}"; port="${entry##*:}"
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://localhost:$port/health" 2>/dev/null || echo '---')"
    printf "   %-11s :%-5s → %s\n" "$svc" "$port" "$code"
  done
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://localhost:5173/" 2>/dev/null || echo '---')"
  printf "   %-11s :%-5s → %s\n" "frontend" "5173" "$code"
  echo "   (200 = 정상 · 000/--- = 부팅중이거나 죽음 → .devlogs/<svc>.log 확인)"
}

cmd_down(){ say "전체 종료…"; stop_tracked; ok "종료 완료."; }
cmd_logs(){ tail -n 40 -f "$LOGDIR/${2:-account}.log"; }

case "${1:-up}" in
  up)     cmd_up ;;
  down)   cmd_down ;;
  status) cmd_status ;;
  logs)   cmd_logs "$@" ;;
  *) die "사용법: $0 {up|down|status|logs <svc>}" ;;
esac
