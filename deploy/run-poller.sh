#!/usr/bin/env bash
# 폴러 서비스 1개를 compose로 1회 실행 (host cron이 호출). 로그 + 중복실행 방지 + 종료코드 기록.
#   사용: deploy/run-poller.sh <poller-oasis|poller-deal-timesale|poller-deal-closesale|poller-recipe|poller-es-recipes|poller-price-matview|poller-kurly>
# 이미지는 Harbor에서 pre-pull됨(deploy/install-pollers.sh). compose가 repo 루트 .env를 읽음.
set -euo pipefail

SVC="${1:?사용법: run-poller.sh <poller-oasis|poller-deal-timesale|poller-deal-closesale|poller-recipe|poller-es-recipes|poller-price-matview|poller-kurly>}"
case "$SVC" in
  poller-oasis|poller-deal-timesale|poller-deal-closesale|poller-recipe|poller-es-recipes|poller-price-matview|poller-kurly) ;;
  *) echo "지원하지 않는 poller: $SVC" >&2; exit 2 ;;
esac
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${FB_POLLER_LOG_DIR:-/var/log/fb-pollers}"
# 기본 로그 경로가 생성 불가/쓰기불가면(예: /var/log 권한) repo-로컬로 폴백.
# ('mkdir -p'는 존재하나 쓰기불가인 디렉토리에도 0을 반환하므로 -w까지 확인)
if ! mkdir -p "$LOG_DIR" 2>/dev/null || [ ! -w "$LOG_DIR" ]; then
  LOG_DIR="$REPO/.poller-logs"
  mkdir -p "$LOG_DIR"
fi
LOG="$LOG_DIR/${SVC}.log"
LOCK="${TMPDIR:-/tmp}/fb-poller-${SVC}.lock"
METRICS_DIR="${FB_POLLER_METRICS_DIR:-/var/lib/node_exporter/textfile_collector}"
METRICS_FILE="$METRICS_DIR/fb_poller_${SVC#poller-}.prom"
SUCCESS_STATE="$METRICS_DIR/.fb_poller_${SVC#poller-}.last_success"
ENVIRONMENT="${ENVIRONMENT:-development}"
case "$ENVIRONMENT" in
  local|development|staging|production) ;;
  *) ENVIRONMENT="development" ;;
esac

log_event() {
  local level="$1" event="$2" message="$3"
  local result="${4:-}" exit_code="${5:-}" record_count="${6:-}"
  {
    printf '{"timestamp":"%s","level":"%s","service":"data-pipeline","environment":"%s","event":"%s","message":"%s","component":"%s"' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$level" "$ENVIRONMENT" "$event" "$message" "$SVC"
    [ -z "$result" ] || printf ',"result":"%s"' "$result"
    [ -z "$exit_code" ] || printf ',"error_code":"exit_%s"' "$exit_code"
    [ -z "$record_count" ] || printf ',"record_count":%s' "$record_count"
    printf '}\n'
  } | tee -a "$LOG" >&2
}

# flock: 직전 실행이 안 끝났으면(예: 컬리 브라우저 행) 이번 회차 스킵 — 중첩 실행 방지
exec 9>"$LOCK"
if ! flock -n 9; then
  log_event "WARNING" "poller_skipped" "poller skipped because prior run holds the lock" "skipped"
  exit 0
fi

log_event "INFO" "poller_started" "poller execution started"
cd "$REPO"
started_at="$(date +%s)"
run_output="$(mktemp "${TMPDIR:-/tmp}/fb-poller-run.XXXXXX")"
trap 'rm -f "$run_output"' EXIT

set +e
docker compose --profile poller run --rm "$SVC" 2>&1 | tee -a "$LOG" "$run_output"
rc="${PIPESTATUS[0]}"
set -e

finished_at="$(date +%s)"
duration="$((finished_at - started_at))"
records="$(awk '
  /"event":"(crawler_succeeded|kafka_produce_succeeded|es_reindex_succeeded)"/ {
    line = $0
    sub(/^.*"record_count":/, "", line)
    sub(/[^0-9].*$/, "", line)
    n += line + 0
  }
  # 만개 크롤러는 구조화 이벤트 대신 이 평문 한 줄로 건수를 알린다
  # (crawler/10k_recipe/10k_recipe_crawler.py). 이걸 안 읽어서 poller-recipe 는
  # 101건을 produce 하고도 메트릭이 늘 0 이었다 → 0건 크롤과 구분 불가.
  # 중복집계 없음: 10k 는 JSON 이벤트를 안 내고, 다른 폴러는 이 평문을 안 낸다.
  /^FB_POLLER_RECORDS [0-9]+$/ { n += $2 }
  END {print n + 0}
' "$run_output")"
http_403="$(grep -Eic '(^|[^0-9])403([^0-9]|$)' "$run_output" || true)"
http_429="$(grep -Eic '(^|[^0-9])429([^0-9]|$)' "$run_output" || true)"
timeouts="$(grep -Eic 'timeout|timed out' "$run_output" || true)"
parsing="$(grep -Eic '파싱 (실패|오류)|parse error|parsing error' "$run_output" || true)"

if [ "$rc" -eq 0 ]; then
  success=1
  last_success="$finished_at"
else
  success=0
  last_success="$(cat "$SUCCESS_STATE" 2>/dev/null || echo 0)"
fi

if mkdir -p "$METRICS_DIR" 2>/dev/null && [ -w "$METRICS_DIR" ]; then
  [ "$success" -eq 0 ] || printf '%s\n' "$last_success" >"$SUCCESS_STATE"
  metrics_tmp="$(mktemp "$METRICS_DIR/.fb-poller.XXXXXX")"
  {
    echo '# HELP fb_poller_last_run_success 마지막 poller 실행의 성공 여부(1=성공)'
    echo '# TYPE fb_poller_last_run_success gauge'
    printf 'fb_poller_last_run_success{poller="%s"} %s\n' "$SVC" "$success"
    echo '# HELP fb_poller_last_run_timestamp_seconds 마지막 poller 실행 종료 Unix 시각'
    echo '# TYPE fb_poller_last_run_timestamp_seconds gauge'
    printf 'fb_poller_last_run_timestamp_seconds{poller="%s"} %s\n' "$SVC" "$finished_at"
    echo '# HELP fb_poller_last_success_timestamp_seconds 마지막 성공 Unix 시각'
    echo '# TYPE fb_poller_last_success_timestamp_seconds gauge'
    printf 'fb_poller_last_success_timestamp_seconds{poller="%s"} %s\n' "$SVC" "$last_success"
    echo '# HELP fb_poller_last_run_duration_seconds 마지막 poller 실행시간'
    echo '# TYPE fb_poller_last_run_duration_seconds gauge'
    printf 'fb_poller_last_run_duration_seconds{poller="%s"} %s\n' "$SVC" "$duration"
    echo '# HELP fb_poller_last_run_records 마지막 실행에서 Kafka로 발행한 레코드 수'
    echo '# TYPE fb_poller_last_run_records gauge'
    printf 'fb_poller_last_run_records{poller="%s"} %s\n' "$SVC" "$records"
    echo '# HELP fb_poller_last_run_failures 마지막 실행 로그에서 발견한 실패 유형 수'
    echo '# TYPE fb_poller_last_run_failures gauge'
    printf 'fb_poller_last_run_failures{poller="%s",reason="http_403"} %s\n' "$SVC" "$http_403"
    printf 'fb_poller_last_run_failures{poller="%s",reason="http_429"} %s\n' "$SVC" "$http_429"
    printf 'fb_poller_last_run_failures{poller="%s",reason="timeout"} %s\n' "$SVC" "$timeouts"
    printf 'fb_poller_last_run_failures{poller="%s",reason="parsing"} %s\n' "$SVC" "$parsing"
  } >"$metrics_tmp"
  # mktemp 기본 권한(0600)으로는 컨테이너의 node-exporter가 읽지 못한다.
  # 최종 배치 전 공개 읽기 권한을 부여해 textfile collector가 수집할 수 있게 한다.
  chmod 0644 "$metrics_tmp"
  mv "$metrics_tmp" "$METRICS_FILE"
else
  log_event "WARNING" "poller_metrics_unavailable" "poller metrics directory is not writable" "failure"
fi

if [ "$rc" -eq 0 ]; then
  log_event "INFO" "poller_succeeded" "poller execution completed" "success" "" "$records"
else
  log_event "ERROR" "poller_failed" "poller execution failed" "failure" "$rc" "$records"
  exit "$rc"
fi
