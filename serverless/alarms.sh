#!/usr/bin/env bash
# mp-ai 알람 — 생성/갱신 (멱등). 🔴 **Terraform 이 아니다. 그럴 수 없다.**
#
# ══ 왜 스크립트인가 ═══════════════════════════════════════════════════════════
#
# Terraform 으로 짰다가 되돌렸다(2026-08-17). 알람 자체는 잘 만들어졌는데 **그 다음 `plan` 이
# 매번 죽었다** — 프로바이더가 refresh 때 태그를 읽는데 `cloudwatch:ListTagsForResource` 가
# `mp-ai-dev` 에 없다:
#
#     Error: listing tags for CloudWatch Metric Alarm (...): AccessDenied
#
# 🔴 자원 하나가 **스택 전체를 못 쓰게** 만든다 — 그 상태로는 함수 배포도 못 한다.
#    ⇒ 알람을 스택 밖으로 뺐다. 레포의 선례와 같은 판단이다:
#      `infra/iam/mp-ai/apply.sh` 머리말 — *"정책 문서를 레포에 두고 스크립트로만 적용한다.
#       누가 무엇을 줬는지는 git 이 답한다."*
#
# 🔵 되돌리는 조건 = `mp-ai-dev` 에 `cloudwatch:ListTagsForResource`·`TagResource` 를
#    `alarm:mp-ai-*` 로 더하면 Terraform 으로 옮길 수 있다. 그때까지는 이 파일이 정본이다.
#
# ══ 왜 알람이 필요한가 ═══════════════════════════════════════════════════════
#
# 2026-08-17 하루에 쫓은 결함이 전부 «조용한 실패» 였다:
#   · 임프레션이 `except: return 0` 으로 삼켜져 **라벨이 0건인 채 한 달**
#   · SG 규칙이 5분 만에 지워졌는데 **아무도 몰랐다**
#   · Loki·Tempo 가 **23시간** 죽어 있었다
# 🔴 Lambda 는 파드보다 더 심하다 — `CrashLoopBackOff` 처럼 눈에 띄는 상태가 없다.
#    죽으면 **그냥 아무 일도 안 일어난다.**
#
# 🔴 그리고 이 배선은 특히 조용히 끊긴다(C-85 의 대가) — PG·ES 를 **노드 사설 IP + NodePort**
#    로 잡으므로 MNG 롤링 업그레이드로 두 노드가 동시에 교체되면 주소가 죽는다.
#    대시보드는 nginx 502 알림으로 막았고, **여기서는 이 스크립트의 ① 알람이 그 자리**다.
#
# 사용:  ALERT_EMAILS="a@b.com,c@d.com" serverless/alarms.sh
#        serverless/alarms.sh --dry-run
set -euo pipefail
export AWS_PAGER=""
REGION=${AWS_REGION:-ap-northeast-2}
DRY=${1:-}

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
TOPIC="arn:aws:sns:${REGION}:${ACCOUNT}:mp-ai-alerts"

run() {
  if [ "$DRY" = "--dry-run" ]; then echo "   [dry-run] $*"; else "$@" >/dev/null; fi
}

# 🔴 구독자가 없으면 알람은 장식이다 — 그 상태를 **끝에서 크게 경고**한다(아래).
if [ -n "${ALERT_EMAILS:-}" ]; then
  echo "▶ 구독 등록"
  IFS=',' read -ra MAILS <<< "$ALERT_EMAILS"
  for m in "${MAILS[@]}"; do
    run aws sns subscribe --region "$REGION" --topic-arn "$TOPIC" --protocol email --notification-endpoint "$m"
    echo "   $m  ⚠️ 확인 메일을 눌러야 활성화된다(그전엔 PendingConfirmation)"
  done
fi

# ── ① 함수가 죽는다 ─────────────────────────────────────────────────────────
# 🔴 **임계값이 1 이다** — «몇 건 이상» 이 아니라 «한 건이라도». 배치는 하루 1회라 평균을 내면
#    1건 실패가 0.0x 로 묻힌다.
# 🔵 `notBreaching` — 호출이 없는 구간은 정상이다. 안 그러면 배치가 안 도는 23시간 내내
#    INSUFFICIENT_DATA 로 울려서 **진짜 실패가 왔을 때 아무도 안 본다**(알람 피로).
echo "▶ ① 함수 오류"
for fn in $(aws lambda list-functions --region "$REGION" \
              --query "Functions[?starts_with(FunctionName, 'mp-ai')].FunctionName" --output text); do
  run aws cloudwatch put-metric-alarm --region "$REGION" \
    --alarm-name "${fn}-errors" \
    --alarm-description "${fn} raised errors. Check CloudWatch Logs for the stack trace." \
    --namespace AWS/Lambda --metric-name Errors \
    --dimensions "Name=FunctionName,Value=${fn}" \
    --statistic Sum --period 300 --evaluation-periods 1 \
    --threshold 1 --comparison-operator GreaterThanOrEqualToThreshold \
    --treat-missing-data notBreaching \
    --alarm-actions "$TOPIC" --ok-actions "$TOPIC"
  echo "   ${fn}-errors"
done

for q in video ocr; do
  # ── ② 잡이 죽어서 쌓인다 ────────────────────────────────────────────────
  # 🔴 워커가 실패해도 **접수는 계속 202 를 준다.** 유저는 «접수됐다» 를 보고 기다리는데
  #    아무도 처리하지 않는 상태가 된다 — DLQ 가 그 유일한 신호다.
  run aws cloudwatch put-metric-alarm --region "$REGION" \
    --alarm-name "mp-ai-${q}-dlq-not-empty" \
    --alarm-description "mp-ai-${q} jobs landed in the DLQ. Users are waiting on jobs nobody processed." \
    --namespace AWS/SQS --metric-name ApproximateNumberOfMessagesVisible \
    --dimensions "Name=QueueName,Value=mp-ai-${q}-jobs-dlq" \
    --statistic Maximum --period 300 --evaluation-periods 1 \
    --threshold 0 --comparison-operator GreaterThanThreshold \
    --treat-missing-data notBreaching \
    --alarm-actions "$TOPIC" --ok-actions "$TOPIC"

  # ── ③ 큐가 안 빠진다 (워커가 안 깨어난다) ───────────────────────────────
  # 🔵 ②와 **다른 고장**이다 — ②는 «처리하다 죽었다», 이건 «아무도 안 가져간다».
  #    이벤트 소스 매핑이 Disabled 로 떨어지거나 워커 권한이 빠지면 이렇게 되는데,
  #    그때 **DLQ 는 조용하다**(재시도 자체가 없으니까).
  # 🔵 900초 = 워커 타임아웃(150s·120s)의 여러 배 — «느린 것» 과 «안 도는 것» 이 갈린다.
  run aws cloudwatch put-metric-alarm --region "$REGION" \
    --alarm-name "mp-ai-${q}-queue-stalled" \
    --alarm-description "Oldest message in mp-ai-${q}-jobs is aging. The worker may not be consuming." \
    --namespace AWS/SQS --metric-name ApproximateAgeOfOldestMessage \
    --dimensions "Name=QueueName,Value=mp-ai-${q}-jobs" \
    --statistic Maximum --period 300 --evaluation-periods 2 \
    --threshold 900 --comparison-operator GreaterThanThreshold \
    --treat-missing-data notBreaching \
    --alarm-actions "$TOPIC" --ok-actions "$TOPIC"
  echo "   mp-ai-${q}-dlq-not-empty · mp-ai-${q}-queue-stalled"
done

echo
N=$(aws cloudwatch describe-alarms --region "$REGION" --alarm-name-prefix mp-ai- \
      --query "length(MetricAlarms)" --output text)
SUBS=$(aws sns list-subscriptions-by-topic --region "$REGION" --topic-arn "$TOPIC" \
      --query "length(Subscriptions[?SubscriptionArn!='PendingConfirmation'])" --output text 2>/dev/null || echo 0)
echo "알람 ${N}개 · 확인된 구독 ${SUBS}건"
if [ "$SUBS" = "0" ]; then
  echo "🔴 구독이 0건이다 — 알람 ${N}개가 **아무에게도 안 간다.**"
  echo "   ALERT_EMAILS=... 로 다시 돌리고, 받은 확인 메일을 반드시 누를 것."
  echo "   (이건 오늘 우리를 괴롭힌 «조용한 실패» 와 같은 모양이다.)"
fi
