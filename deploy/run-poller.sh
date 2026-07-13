#!/usr/bin/env bash
# 폴러 서비스 1개를 compose로 1회 실행 (host cron이 호출). 로그 + 중복실행 방지 + 종료코드 기록.
#   사용: deploy/run-poller.sh <poller-oasis|poller-deal|poller-recipe|poller-kurly>
# 이미지는 Harbor에서 pre-pull됨(deploy/install-pollers.sh). compose가 repo 루트 .env를 읽음.
set -euo pipefail

SVC="${1:?사용법: run-poller.sh <poller-oasis|poller-deal|poller-recipe|poller-kurly>}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${FB_POLLER_LOG_DIR:-/var/log/fb-pollers}"
mkdir -p "$LOG_DIR" 2>/dev/null || LOG_DIR="$REPO/.poller-logs" && mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/${SVC}.log"
LOCK="${TMPDIR:-/tmp}/fb-poller-${SVC}.lock"

log() { echo "[$(date -Is)] $*" | tee -a "$LOG" >&2; }

# flock: 직전 실행이 안 끝났으면(예: 컬리 브라우저 행) 이번 회차 스킵 — 중첩 실행 방지
exec 9>"$LOCK"
if ! flock -n 9; then
  log "SKIP ${SVC} — 이전 실행이 아직 진행 중 (lock held)"
  exit 0
fi

log "START ${SVC}"
cd "$REPO"
if docker compose --profile poller run --rm "$SVC" >>"$LOG" 2>&1; then
  log "DONE  ${SVC} (exit 0)"
else
  rc=$?
  log "FAIL  ${SVC} (exit ${rc})"
  exit "$rc"
fi
