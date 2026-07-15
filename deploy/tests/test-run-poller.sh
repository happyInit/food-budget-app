#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/log" "$TMP/metrics"

cat >"$TMP/bin/docker" <<'FAKE_DOCKER'
#!/usr/bin/env bash
echo 'HTTP 429 test marker'
echo 'FB_POLLER_RECORDS 12'
exit "${FAKE_DOCKER_EXIT:-0}"
FAKE_DOCKER
chmod +x "$TMP/bin/docker"

export PATH="$TMP/bin:$PATH"
export FB_POLLER_LOG_DIR="$TMP/log"
export FB_POLLER_METRICS_DIR="$TMP/metrics"

"$ROOT/deploy/run-poller.sh" poller-oasis
METRICS="$TMP/metrics/fb_poller_oasis.prom"
grep -q 'fb_poller_last_run_success{poller="poller-oasis"} 1' "$METRICS"
grep -q 'fb_poller_last_run_records{poller="poller-oasis"} 12' "$METRICS"
grep -q 'reason="http_429"} 1' "$METRICS"
FIRST_SUCCESS="$(awk '/last_success_timestamp_seconds\{/{print $2}' "$METRICS")"

export FAKE_DOCKER_EXIT=7
if "$ROOT/deploy/run-poller.sh" poller-oasis; then
  echo '실패 poller가 성공 종료코드를 반환했습니다.' >&2
  exit 1
fi
grep -q 'fb_poller_last_run_success{poller="poller-oasis"} 0' "$METRICS"
grep -q "fb_poller_last_success_timestamp_seconds{poller=\"poller-oasis\"} $FIRST_SUCCESS" "$METRICS"

echo 'run-poller metrics test: PASS'
