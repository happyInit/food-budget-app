#!/usr/bin/env bash
# AWS(EKS) Stage1 부하시험 — 준비·실행·원복을 한 번에.
#
# 실행:  loadtest/run_aws_stage1.sh run           # 500 VU (기본)
#        VUS=1500 loadtest/run_aws_stage1.sh run  # Karpenter 유발 최대치
#        loadtest/run_aws_stage1.sh check         # 전제만 확인하고 종료(부하 안 검)
#
# ── 🔴 이 스크립트가 존재하는 이유 = 부하를 걸기 전에 **되돌려야 할 것이 두 개** 생긴다 ──
#   ① AWS WAF 레이트룰(`mp-waf-public`)  ② account·recipe HPA 상한
# 둘 다 원복이 작업의 일부다(`variables.tf` 의 waf_rate_limit_per_5min 주석이 못박은 조건).
# 그래서 원복을 **trap 에 건다** — Ctrl-C·k6 abortOnFail·중간 실패 어느 쪽이든 되돌아간다.
set -uo pipefail

MODE="${1:-check}"
HOST="${HOST:-aws.mealbong.cloud}"
VUS="${VUS:-500}"
NUSERS="${NUSERS:-200}"          # 🔴 AWS PG 실측 = loadtest-pool 200명. 넘겨 잡으면 없는 계정으로 로그인 실패한다.
# 🔴 setup 단계의 로그인 페이스(분당). account 스로틀은 IP당 100/분 · **파드별 in-memory** 라
#    파드 2개면 실효 200/분이다. 120 은 그 안쪽의 보수값 — 근거는 stage1_journey.js 의 setup 주석.
#    ⚠️ setup 이 NUSERS/perMin 분만큼 걸린다(200/120 ≈ 100초). 그만큼 시험 시작이 늦다.
LOGIN_PER_MIN="${LOGIN_PER_MIN:-120}"
HPA_MAX="${HPA_MAX:-8}"
WAF_LIMIT_TEST="${WAF_LIMIT_TEST:-5000000}"
# 🔴 AWS 기본 고원은 **8분**이다(온프렘 기본 90초가 아니라). Karpenter 노드가 EC2 기동 →
#    부트스트랩 → 조인까지 60~90초 걸리므로, 90초 고원에서는 노드가 Ready 되는 순간 시험이 끝난다.
#    그러면 "NodeClaim 은 생겼는데 처리량은 그대로"라는 **측정 실패**가 나온다.
RAMP="${RAMP:-1m}"
PLATEAU="${PLATEAU:-8m}"
RAMPDN="${RAMPDN:-30s}"
TF_DIR="${TF_DIR:-/home/kevin/projects/wt-team/infra/terraform/aws-platform}"
K6="${K6:-/mnt/c/temp/k6.exe}"
SCRIPT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/stage1_journey.js"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { printf '\033[31mFATAL: %s\033[0m\n' "$*" >&2; exit 1; }

# ── 원복 (trap) ───────────────────────────────────────────────────────────────
WAF_RAISED=0
HPA_RAISED=0
revert() {
  local rc=$?
  say "원복"
  if [ "$HPA_RAISED" = "1" ]; then
    # 🔴 상수(구 `4`)로 되돌리지 않는다 — **시험 직전 값**으로 되돌린다.
    #    config 레포가 max 를 8 로 올린 뒤(2026-08-17)에도 4 로 되돌리면 라이브가 git 과
    #    어긋나는데, 앱 Application 은 selfHeal 이 꺼져 있어 **ArgoCD 가 고쳐 주지 않는다.**
    #    즉 원복이 드리프트를 만든다. 값을 기억했다 그대로 복구한다.
    for h in mp-account mp-recipe; do
      eval "prev=\${HPA_PREV_${h//-/_}:-}"
      [ -n "$prev" ] || continue
      kubectl -n app patch hpa "$h" -p "{\"spec\":{\"maxReplicas\":$prev}}" >/dev/null 2>&1 \
        && echo "  HPA $h  max -> $prev (시험 전 값)"
    done
  fi
  if [ "$WAF_RAISED" = "1" ]; then
    echo "  WAF 레이트룰 원복(terraform apply) …"
    ( cd "$TF_DIR" && AWS_PROFILE=mp-platform ~/projects/.tfbin/terraform apply \
        -input=false -no-color -auto-approve >/dev/null 2>&1 ) \
      && echo "  WAF limit -> 2000 (기본값)" \
      || echo "  🔴 WAF 원복 실패 — 수동 확인 필요: cd $TF_DIR && terraform apply"
  fi
  # Karpenter 노드는 consolidateAfter=5m·WhenEmpty 라 파드가 빠지면 스스로 정리된다(수동 삭제 불요).
  echo "  Karpenter 노드는 5분 뒤 자동 축소(consolidationPolicy=WhenEmpty)"
  exit $rc
}

# ── 전제 확인 ─────────────────────────────────────────────────────────────────
say "전제 확인"
[ -x "$K6" ] || die "k6 없음: $K6"
[ -f "$SCRIPT_SRC" ] || die "k6 스크립트 없음: $SCRIPT_SRC"
command -v kubectl >/dev/null || die "kubectl 없음"
kubectl -n app get hpa mp-account mp-recipe >/dev/null 2>&1 || die "HPA 조회 실패 — kubectl 컨텍스트가 EKS 인지 확인"
[ -d "$TF_DIR" ] || die "terraform 디렉터리 없음: $TF_DIR (TF_DIR=... 로 지정)"

for p in '/api/prices/hotdeals?limit=20' '/api/recipes?q=%EA%B9%80%EC%B9%98'; do
  c=$(curl -s -o /dev/null -w '%{http_code}' "https://$HOST$p")
  [ "$c" = "200" ] || die "$p -> HTTP $c (기대 200)"
  printf '  %-42s %s\n' "$p" "$c"
done
c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "https://$HOST/api/auth/login" \
      -H 'Content-Type: application/json' \
      -d '{"email":"loadtest-pool-0001@mealbong.cloud","password":"LoadTest2026!"}')
[ "$c" = "200" ] || die "로그인 -> HTTP $c (기대 200). 유저 풀 시드 필요할 수 있음: seed_users.js"
echo "  로그인                                     $c"

pool=$(kubectl -n data exec pg-1 -c postgres -- psql -U postgres -d foodbudget -tAc \
        "select count(*) from account.app_user where email like 'loadtest-pool-%'" 2>/dev/null | tr -d ' \r')
echo "  loadtest-pool 유저 수                      ${pool:-?} (NUSERS=$NUSERS)"
if [ -n "${pool:-}" ] && [ "$pool" -lt "$NUSERS" ]; then
  die "유저 풀($pool) < NUSERS($NUSERS) — NUSERS 를 낮추거나 seed_users.js 로 더 시드"
fi

say "현재 용량"
kubectl get nodes -o custom-columns='NODE:.metadata.name,TYPE:.metadata.labels.node\.kubernetes\.io/instance-type,ZONE:.metadata.labels.topology\.kubernetes\.io/zone,KARPENTER:.metadata.labels.karpenter\.sh/nodepool' --no-headers
kubectl -n app get hpa mp-account mp-recipe --no-headers

if [ "$MODE" != "run" ]; then
  echo
  echo "check 모드 — 부하는 걸지 않았다. 실제 실행은:  $0 run"
  exit 0
fi

trap revert EXIT INT TERM

# ── ① WAF 레이트룰 한시 상향 ───────────────────────────────────────────────────
# 🔴 이걸 안 하면 3초 만에 차단되고, 그 뒤로는 우리 스택이 아니라 WAF 403 을 측정한다.
#    기본 2000/5분/IP = 초당 6.7건인데 500 VU 는 초당 약 750건을 **한 IP 에서** 보낸다.
say "① WAF 레이트룰 한시 상향 (2000 -> $WAF_LIMIT_TEST /5분/IP)"
( cd "$TF_DIR" && AWS_PROFILE=mp-platform ~/projects/.tfbin/terraform apply \
    -input=false -no-color -auto-approve -var "waf_rate_limit_per_5min=$WAF_LIMIT_TEST" >/dev/null 2>&1 ) \
  || die "WAF 상향 실패"
WAF_RAISED=1
echo "  적용됨 (원복은 종료 시 자동)"

# ── ② HPA 상한 상향 ───────────────────────────────────────────────────────────
# 🔴 max=4 로는 Karpenter 가 안 뜬다 — 여유 CPU 1370m 안에 증가분이 다 들어가서
#    Pending 파드가 안 생기고, Karpenter 는 Pending 파드에만 반응한다.
say "② HPA 상한 상향 (-> $HPA_MAX)"
for h in mp-account mp-recipe; do
  # 원복용으로 **먼저 기억**한다(patch 뒤에 읽으면 이미 늦다).
  eval "HPA_PREV_${h//-/_}=\$(kubectl -n app get hpa \"$h\" -o jsonpath='{.spec.maxReplicas}')"
  kubectl -n app patch hpa "$h" -p "{\"spec\":{\"maxReplicas\":$HPA_MAX}}" >/dev/null \
    || die "$h HPA patch 실패"
done
HPA_RAISED=1
kubectl -n app get hpa mp-account mp-recipe --no-headers

# ── ③ k6 실행 ─────────────────────────────────────────────────────────────────
say "③ k6 실행 (VUS=$VUS · NUSERS=$NUSERS · 고원 $PLATEAU · HOST=$HOST)"
cp "$SCRIPT_SRC" /mnt/c/temp/ || die "스크립트 복사 실패"
# 배경에서 스케일 변화를 같이 찍는다 — k6 요약만 보면 "왜 빨라졌나"를 못 읽는다.
( while :; do
    printf '%s  nodes=%s  account=%s  recipe=%s\n' "$(date +%H:%M:%S)" \
      "$(kubectl get nodes --no-headers 2>/dev/null | wc -l)" \
      "$(kubectl -n app get hpa mp-account -o jsonpath='{.status.currentReplicas}' 2>/dev/null)" \
      "$(kubectl -n app get hpa mp-recipe  -o jsonpath='{.status.currentReplicas}' 2>/dev/null)"
    sleep 20
  done ) > /tmp/mp-loadtest-scale.log 2>&1 &
WATCH_PID=$!

"$K6" run -e "IP=none" -e "HOST=$HOST" -e "VUS=$VUS" -e "NUSERS=$NUSERS" \
      -e "RAMP=$RAMP" -e "PLATEAU=$PLATEAU" -e "RAMPDN=$RAMPDN" \
      -e "LOGIN_PER_MIN=$LOGIN_PER_MIN" \
      --summary-trend-stats 'avg,min,med,p(95),p(99),max' \
      'C:\temp\stage1_journey.js'
kill "$WATCH_PID" 2>/dev/null

# ── ④ 결과 수집 ───────────────────────────────────────────────────────────────
say "④ 스케일 결과"
kubectl get nodes -o custom-columns='NODE:.metadata.name,TYPE:.metadata.labels.node\.kubernetes\.io/instance-type,ZONE:.metadata.labels.topology\.kubernetes\.io/zone,KARPENTER:.metadata.labels.karpenter\.sh/nodepool' --no-headers
kubectl -n app get hpa mp-account mp-recipe --no-headers
echo "-- Karpenter 가 만든 NodeClaim --"
kubectl get nodeclaims --no-headers 2>/dev/null || echo "  (없음 = Karpenter 미발동)"
echo "-- 부하 중 Pending 이었던 파드 --"
kubectl -n app get events --sort-by=.lastTimestamp 2>/dev/null | grep -i 'FailedScheduling\|TriggeredScaleUp\|Nominated' | tail -10 || true
echo "-- 시간별 스케일 추이 (/tmp/mp-loadtest-scale.log) --"
cat /tmp/mp-loadtest-scale.log 2>/dev/null | tail -40 || true
