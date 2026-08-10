#!/usr/bin/env bash
# 팀 RBAC 검증 — 읽기 전용(`kubectl auth can-i` 만 쓴다. 아무것도 바꾸지 않는다).
#
# 용도
#   1) 적용 **전** 에 돌려 현행(내장 edit) 기준선을 뜬다
#   2) 적용 **후** 에 다시 돌려 의도대로 좁혀졌는지 본다
#   3) diff 를 PR·문서에 붙인다  (= 계획 §12 "적용 순서 2단계")
#
# 사용
#   ssh ubuntu@<master> 'sudo bash -s' < verify-rbac.sh            # 표 + 판정
#   ssh ubuntu@<master> 'sudo bash -s' < verify-rbac.sh -- --list  # can-i --list 원문(diff 용)
#
# 🔴 임퍼소네이션(`--as`)이 되려면 실행 주체가 admin 이어야 한다. master 의 admin.conf 로 돈다.
set -uo pipefail

KUBECTL="${KUBECTL:-kubectl}"
NS_USERS="${NS_USERS:-mp-users}"
MODE="${1:-table}"

# 사람 → 검사할 ns (defaults/main.yml 의 mp_team_rbac 와 맞춰 둘 것)
PEOPLE=(
  "geonu:app"
  "geonu:pipeline"
  "jungeun:pipeline"
  "junghyun:observability"
)

subj() { echo "system:serviceaccount:${NS_USERS}:$1"; }

if [ "$MODE" = "--list" ]; then
  for p in "${PEOPLE[@]}"; do
    who="${p%%:*}"; ns="${p##*:}"
    echo "===== ${who} @ ${ns} ====="
    $KUBECTL auth can-i --list --as="$(subj "$who")" -n "$ns"
    echo
  done
  exit 0
fi

# 항목: "verb|resource|기대값"
#   기대값 = 커스텀 롤 적용 **후** 에 나와야 하는 값. 적용 전이면 MISMATCH 가 잔뜩 나오는 게 정상이다.
CHECKS_DENY=(
  "get|secrets"                     # ESO 가 만든다 · 사람이 읽을 이유 0
  "create|secrets"
  "create|serviceaccounts"          # IRSA/Pod Identity 다리 (C-24)
  "create|serviceaccounts/token"    # ★ 가장 중요 — EKS 에서 그 SA 의 IAM 롤이 된다
  "impersonate|serviceaccounts"
  "create|pods"                     # 있으면 Secret 마운트한 디버그 파드를 띄울 수 있다
  "create|configmaps"               # GitOps — 정본은 git
  "create|persistentvolumeclaims"
  "create|externalsecrets.external-secrets.io"   # ★ 0-14b 전까지는 fb-secrets 전량 우회 경로
  "create|pushsecrets.external-secrets.io"
  "create|rolebindings.rbac.authorization.k8s.io"
)
CHECKS_ALLOW=(
  "get|pods"
  "get|pods/log"
  "list|events"
  "patch|deployments.apps"
  "delete|pods"
)
# 관측 티어는 워크로드 쓰기를 **안 준다** (실측 연쇄 — 계획 §11)
OBS_DENY=("create|pods/exec" "patch|deployments.apps" "patch|statefulsets.apps")
DEV_ALLOW=("create|pods/exec" "create|pods/portforward")
PIPE_ALLOW=("create|jobs.batch" "delete|jobs.batch" "patch|cronjobs.batch")

fail=0; pass=0
# 🔴 `kubectl auth can-i <verb> <resource>/<X>` 에서 X 는 **서브리소스가 아니라 리소스 이름**이다.
#    `create pods/exec` 는 "exec 라는 이름의 pod 를 만들 수 있나"를 묻는다 — 우리가 알고 싶은 것과 다르다.
#    서브리소스는 반드시 `--subresource=` 로 물어야 한다. (2026-08-10 실측으로 확인)
#    항목 표기: "resource" 또는 "resource/subresource" — 여기서 후자를 --subresource 로 번역한다.
check() { # who ns verb res[/subres] want
  local who="$1" ns="$2" verb="$3" res="$4" want="$5"
  local base="${res%%/*}" sub="" args=()
  if [ "$res" != "$base" ]; then sub="${res#*/}"; args=(--subresource="$sub"); fi
  local got; got=$($KUBECTL auth can-i "$verb" "$base" "${args[@]}" --as="$(subj "$who")" -n "$ns" 2>/dev/null)
  if [ "$got" = "$want" ]; then pass=$((pass+1)); mark="  ok"
  else fail=$((fail+1)); mark="MISMATCH"; fi
  printf "%-8s %-14s %-10s %-46s want=%-3s got=%-3s %s\n" \
    "$who" "$ns" "$verb" "$res" "$want" "$got" "$mark"
}

for p in "${PEOPLE[@]}"; do
  who="${p%%:*}"; ns="${p##*:}"
  echo "--- ${who} @ ${ns} ---"
  for c in "${CHECKS_DENY[@]}";  do check "$who" "$ns" "${c%%|*}" "${c##*|}" no;  done
  for c in "${CHECKS_ALLOW[@]}"; do
    # 관측 티어는 deployments patch 를 안 받는다 → ALLOW 목록에서 예외 처리
    if [ "$ns" = "observability" ] && [ "${c##*|}" = "deployments.apps" ]; then continue; fi
    check "$who" "$ns" "${c%%|*}" "${c##*|}" yes
  done
  if [ "$ns" = "observability" ]; then
    for c in "${OBS_DENY[@]}"; do check "$who" "$ns" "${c%%|*}" "${c##*|}" no; done
    check "$who" "$ns" create prometheusrules.monitoring.coreos.com yes
    check "$who" "$ns" create pods/portforward yes
  else
    for c in "${DEV_ALLOW[@]}"; do check "$who" "$ns" "${c%%|*}" "${c##*|}" yes; done
  fi
  if [ "$ns" = "pipeline" ]; then
    for c in "${PIPE_ALLOW[@]}"; do check "$who" "$ns" "${c%%|*}" "${c##*|}" yes; done
  fi
  # ns 경계 — 남의 ns 는 쓰기 불가
  for other in data fb-secrets kube-system argocd; do
    check "$who" "$other" create pods no
    check "$who" "$other" get secrets no
  done
  echo
done

echo "── 종착지 확인: admin 장수 토큰이 사라졌나 ──"
for a in bongsu taehyun; do
  if $KUBECTL -n "$NS_USERS" get secret "${a}-token" >/dev/null 2>&1; then
    echo "  MISMATCH  ${a}-token 이 아직 있다 (만료 없는 cluster-admin 자격증명)"; fail=$((fail+1))
  else
    echo "  ok        ${a}-token 없음"; pass=$((pass+1))
  fi
done

echo
echo "── 레거시 바인딩이 남아 있나 (남아 있으면 커스텀 롤이 무의미해진다) ──"
for ns in app pipeline observability data; do
  out=$($KUBECTL -n "$ns" get rolebinding -o name 2>/dev/null | grep -E 'mp-.*-edit$' || true)
  if [ -n "$out" ]; then echo "  MISMATCH  $ns: $out"; fail=$((fail+1));
  else echo "  ok        $ns 정리됨"; pass=$((pass+1)); fi
done

echo
echo "합계: ok=${pass}  MISMATCH=${fail}"
[ "$fail" -eq 0 ]
