#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/log" "$TMP/metrics"

cat >"$TMP/bin/docker" <<'FAKE_DOCKER'
#!/usr/bin/env bash
if [[ "$*" == *"poller-es-recipes"* ]]; then
  echo '{"timestamp":"2026-07-16T00:00:00Z","level":"INFO","service":"data-pipeline","environment":"test","event":"es_reindex_succeeded","message":"recipe search index rebuild completed","component":"poller-es-recipes","record_count":37}'
  exit "${FAKE_DOCKER_EXIT:-0}"
fi
echo 'HTTP 429 test marker'
echo '{"timestamp":"2026-07-16T00:00:00Z","level":"INFO","service":"data-pipeline","environment":"test","event":"crawler_succeeded","message":"test poller completed","component":"poller-oasis","record_count":12}'
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
grep -q '"event":"poller_succeeded"' "$TMP/log/poller-oasis.log"
grep -q '"record_count":12' "$TMP/log/poller-oasis.log"
FIRST_SUCCESS="$(awk '/last_success_timestamp_seconds\{/{print $2}' "$METRICS")"

"$ROOT/deploy/run-poller.sh" poller-es-recipes
ES_METRICS="$TMP/metrics/fb_poller_es-recipes.prom"
grep -q 'fb_poller_last_run_success{poller="poller-es-recipes"} 1' "$ES_METRICS"
grep -q 'fb_poller_last_run_records{poller="poller-es-recipes"} 37' "$ES_METRICS"
grep -q '"record_count":37' "$TMP/log/poller-es-recipes.log"

export FAKE_DOCKER_EXIT=7
if "$ROOT/deploy/run-poller.sh" poller-oasis; then
  echo '실패 poller가 성공 종료코드를 반환했습니다.' >&2
  exit 1
fi
grep -q 'fb_poller_last_run_success{poller="poller-oasis"} 0' "$METRICS"
grep -q "fb_poller_last_success_timestamp_seconds{poller=\"poller-oasis\"} $FIRST_SUCCESS" "$METRICS"
grep -q '"event":"poller_failed"' "$TMP/log/poller-oasis.log"
grep -q '"error_code":"exit_7"' "$TMP/log/poller-oasis.log"

echo 'run-poller metrics test: PASS'
