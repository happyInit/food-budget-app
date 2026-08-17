#!/usr/bin/env python3
"""mp-ai 알람 — 생성/갱신 (멱등). 🔴 **`serverless/alarms.sh` 의 대체물이다.**

## 왜 셸이 아니라 파이썬인가

`alarms.sh` 는 이 환경에서 **한 번도 돌지 못한다.** aws CLI 2.31.35 + Python 3.14 조합에서
`cloudwatch put-metric-alarm` 이 인자 파싱 전에 죽는다:

    ValueError: unsupported format character ':' (0x3a) at index 696
    ValueError: badly formed help string

CLI 가 도움말 문자열을 `%` 포맷으로 만들다 터지는 **클라이언트 버그**다. 권한도 인자도 문제가
아니라서, 에러 메시지가 원인을 전혀 안 가리킨다.

🔴 그리고 이걸 몰라서 **알람이 도는 줄 알았다.** 기존 알람 7개는 Terraform 시절 산물이었고,
   스크립트로 옮긴 뒤로는 실행이 성공한 적이 없다. 2026-08-18 에 함수가 3→10 으로 늘었는데
   새 7종에 알람이 안 붙는 것을 보고서야 드러났다.
   ⇒ *"스크립트가 있다"* 와 *"스크립트가 돈다"* 는 다르다. 오늘 같은 부류를 여러 번 봤다.

## 왜 Terraform 이 아닌가

`cloudwatch:ListTagsForResource` 가 없어서 프로바이더 refresh 가 죽고, **스택 전체가**
못 쓰게 된다. 권한요청 ②가 오면 Terraform 으로 되돌린다.

사용:  ALERT_EMAILS="a@b.com" serverless/scripts/alarms.py
       serverless/scripts/alarms.py --dry-run
"""
from __future__ import annotations

import os
import sys

import boto3

REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
DRY = "--dry-run" in sys.argv

sts = boto3.client("sts", region_name=REGION)
ACCOUNT = sts.get_caller_identity()["Account"]
TOPIC = f"arn:aws:sns:{REGION}:{ACCOUNT}:mp-ai-alerts"

cw = boto3.client("cloudwatch", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)
sns = boto3.client("sns", region_name=REGION)


def put(**kw):
    kw.setdefault("ActionsEnabled", True)
    kw["AlarmActions"] = [TOPIC]
    kw["OKActions"] = [TOPIC]
    # 🔵 호출이 없는 구간은 정상이다. 안 그러면 배치가 안 도는 23시간 내내 INSUFFICIENT_DATA
    #    로 울려서 **진짜 실패가 왔을 때 아무도 안 본다**(알람 피로).
    kw["TreatMissingData"] = "notBreaching"
    if DRY:
        print(f"   [dry-run] {kw['AlarmName']}")
        return
    cw.put_metric_alarm(**kw)
    print(f"   {kw['AlarmName']}")


if os.environ.get("ALERT_EMAILS"):
    print("▶ 구독 등록")
    for m in [x.strip() for x in os.environ["ALERT_EMAILS"].split(",") if x.strip()]:
        if not DRY:
            sns.subscribe(TopicArn=TOPIC, Protocol="email", Endpoint=m)
        print(f"   {m}  ⚠️ 확인 메일을 눌러야 활성화된다(그전엔 PendingConfirmation)")

# ── ① 함수가 죽는다 ─────────────────────────────────────────────────────────
# 🔴 **임계값이 1 이다** — «몇 건 이상» 이 아니라 «한 건이라도». 배치는 하루 1회라 평균을 내면
#    1건 실패가 0.0x 로 묻힌다.
print("▶ ① 함수 오류")
names = []
for page in lam.get_paginator("list_functions").paginate():
    names += [f["FunctionName"] for f in page["Functions"]
              if f["FunctionName"].startswith("mp-ai")]
for fn in sorted(names):
    put(AlarmName=f"{fn}-errors",
        AlarmDescription=f"{fn} raised errors. Check CloudWatch Logs for the stack trace.",
        Namespace="AWS/Lambda", MetricName="Errors",
        Dimensions=[{"Name": "FunctionName", "Value": fn}],
        Statistic="Sum", Period=300, EvaluationPeriods=1,
        Threshold=1, ComparisonOperator="GreaterThanOrEqualToThreshold")

for q in ("video", "ocr"):
    # ── ② 잡이 죽어서 쌓인다 ────────────────────────────────────────────────
    # 🔴 워커가 실패해도 **접수는 계속 202 를 준다.** 유저는 «접수됐다» 를 보고 기다리는데
    #    아무도 처리하지 않는 상태가 된다 — DLQ 가 그 유일한 신호다.
    print(f"▶ ②③ {q} 큐")
    put(AlarmName=f"mp-ai-{q}-dlq-not-empty",
        AlarmDescription=f"mp-ai-{q} jobs landed in the DLQ. Users are waiting on jobs nobody processed.",
        Namespace="AWS/SQS", MetricName="ApproximateNumberOfMessagesVisible",
        Dimensions=[{"Name": "QueueName", "Value": f"mp-ai-{q}-jobs-dlq"}],
        Statistic="Maximum", Period=300, EvaluationPeriods=1,
        Threshold=0, ComparisonOperator="GreaterThanThreshold")
    # ── ③ 큐가 안 빠진다 (워커가 안 깨어난다) ───────────────────────────────
    # 🔵 ②와 **다른 고장**이다 — ②는 «처리하다 죽었다», 이건 «아무도 안 가져간다».
    #    그때 **DLQ 는 조용하다**(재시도 자체가 없으니까).
    put(AlarmName=f"mp-ai-{q}-queue-stalled",
        AlarmDescription=f"Oldest message in mp-ai-{q}-jobs is aging. The worker may not be consuming.",
        Namespace="AWS/SQS", MetricName="ApproximateAgeOfOldestMessage",
        Dimensions=[{"Name": "QueueName", "Value": f"mp-ai-{q}-jobs"}],
        Statistic="Maximum", Period=300, EvaluationPeriods=2,
        Threshold=900, ComparisonOperator="GreaterThanThreshold")

n = len(cw.get_paginator("describe_alarms").paginate(
    AlarmNamePrefix="mp-ai-").build_full_result()["MetricAlarms"])
subs = [s for s in sns.list_subscriptions_by_topic(TopicArn=TOPIC)["Subscriptions"]
        if s["SubscriptionArn"] != "PendingConfirmation"]
print(f"\n알람 {n}개 · 확인된 구독 {len(subs)}건")
if not subs:
    print(f"🔴 구독이 0건이다 — 알람 {n}개가 **아무에게도 안 간다.**")
    print("   ALERT_EMAILS=... 로 다시 돌리고, 받은 확인 메일을 반드시 누를 것.")
