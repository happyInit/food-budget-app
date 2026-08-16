"""mp-security-notifier — 보안 이벤트 → Slack `#mp-security` (C-65).

## 왜 Alertmanager 를 안 거치나 (C-65 · 편의가 아니라 순환 의존)

이 Lambda 가 나르는 사건(자격증명 이상 사용 · EKS 감사 이상 · 크립토마이닝)은 **클러스터/계정이
이미 이상한 국면**이다. 알림 경로가 방어 대상 안에 있으면 **같이 죽거나 침해자가 끌 수 있다.**
그래서 경로는 분리하고(EventBridge → 여기 → Slack) 창구만 통합한다(같은 Slack).
🟢 경로 A(Prometheus/Loki → Alertmanager → `#mp-alerts`)는 **한 줄도 안 건드린다** — 층이 다르다:
   ① 워크로드 = Prometheus / ② 컨트롤플레인 = EKS 감사로그 / ③ 계정 = CloudTrail·GuardDuty.
   셋은 서로의 사각지대다.

## 보강(enrichment) — 있으면 좋고, 없어도 보낸다

finding 의 주체·시각(±15분)으로 EKS 감사로그(CloudWatch Logs)를 왕복 조회해 발췌를 붙인다.
🔴 **조회가 실패하거나 0건이어도 발송은 강행한다** — 보강은 부가가치지 전제조건이 아니다.
   여기서 예외를 올리면 *"보강이 안 되어서 알림 자체가 안 갔다"* 가 되는데, 그건 이 컴포넌트가
   존재하는 이유와 정반대다.

## 웹훅

Secrets Manager 에서 **호출마다** 읽는다. 캐시하지 않는 이유 = 웹훅을 교체했을 때 재배포 없이
바로 반영되게 하려는 것이고, 호출 빈도가 낮아(보안 이벤트) 비용·지연이 문제가 안 된다.
🔵 이 채널은 **조용한 것이 정상**이다 — 그 성질 자체가 신호라, 시끄럽게 만들지 않는다.
"""
import json
import os
import time
import urllib.request

import boto3

SECRET_NAME = os.environ["SLACK_SECRET_NAME"]
AUDIT_LOG_GROUP = os.environ.get("AUDIT_LOG_GROUP", "")
ENRICH_WINDOW_S = int(os.environ.get("ENRICH_WINDOW_S", "900"))  # ±15분 (C-65)
ENRICH_TIMEOUT_S = int(os.environ.get("ENRICH_TIMEOUT_S", "20"))

_sm = boto3.client("secretsmanager")
_logs = boto3.client("logs")

# GuardDuty severity → Slack 표시. 숫자만 보여주면 사람이 매번 환산해야 한다.
SEVERITY = [(7.0, "🔴", "HIGH"), (4.0, "🟠", "MEDIUM"), (0.0, "🟡", "LOW")]


def _webhook() -> str:
    return _sm.get_secret_value(SecretId=SECRET_NAME)["SecretString"].strip()


def _sev(score) -> tuple:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return ("⚪", "UNKNOWN", 0.0)
    for lo, icon, label in SEVERITY:
        if s >= lo:
            return (icon, label, s)
    return ("⚪", "UNKNOWN", s)


def _enrich(actor: str, when_epoch: float) -> str:
    """EKS 감사로그에서 그 주체의 최근 활동을 뽑는다. 🔴 실패해도 예외를 올리지 않는다."""
    if not AUDIT_LOG_GROUP or not actor:
        return ""
    try:
        q = _logs.start_query(
            logGroupName=AUDIT_LOG_GROUP,
            startTime=int(when_epoch - ENRICH_WINDOW_S),
            endTime=int(when_epoch + ENRICH_WINDOW_S),
            queryString=(
                "fields @timestamp, user.username, verb, objectRef.resource, objectRef.name, responseStatus.code "
                f'| filter @message like /{actor}/ '
                "| sort @timestamp desc | limit 10"
            ),
        )
        qid = q["queryId"]
        deadline = time.time() + ENRICH_TIMEOUT_S
        while time.time() < deadline:
            r = _logs.get_query_results(queryId=qid)
            if r["status"] in ("Complete", "Failed", "Cancelled"):
                break
            time.sleep(1)
        else:
            _logs.stop_query(queryId=qid)
            return "_감사로그 조회 시간초과 — 발송은 계속합니다_"

        rows = r.get("results") or []
        if not rows:
            return "_해당 시간창에 EKS 감사로그 일치 항목 없음_"
        lines = []
        for row in rows[:5]:
            f = {c["field"]: c["value"] for c in row}
            lines.append(
                f"• `{f.get('@timestamp','?')}` {f.get('user.username','?')} "
                f"{f.get('verb','?')} {f.get('objectRef.resource','')}/{f.get('objectRef.name','')} "
                f"→ {f.get('responseStatus.code','')}"
            )
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001 — 🔴 보강 실패가 발송을 막으면 안 된다
        return f"_감사로그 보강 실패({type(exc).__name__}) — 발송은 계속합니다_"


def _guardduty_blocks(d: dict) -> tuple:
    icon, label, score = _sev(d.get("severity"))
    svc = d.get("service") or {}
    actor = (
        ((svc.get("action") or {}).get("awsApiCallAction") or {}).get("remoteIpDetails", {}).get("ipAddressV4")
        or (d.get("resource") or {}).get("accessKeyDetails", {}).get("userName")
        or ""
    )
    title = f"{icon} GuardDuty · {label} ({score})"
    body = [
        f"*{d.get('type','(타입 없음)')}*",
        d.get("description", ""),
        f"계정 `{d.get('accountId','?')}` · 리전 `{d.get('region','?')}`",
    ]
    if actor:
        body.append(f"주체/원격 `{actor}`")
    body.append(
        f"<https://{d.get('region','ap-northeast-2')}.console.aws.amazon.com/guardduty/home"
        f"?region={d.get('region','ap-northeast-2')}#/findings|콘솔에서 원본 보기>"
    )
    return title, "\n".join(x for x in body if x), actor


def _signin_blocks(detail: dict) -> tuple:
    ui = detail.get("userIdentity") or {}
    mfa = ((detail.get("additionalEventData") or {}).get("MFAUsed")) or "?"
    who = ui.get("arn") or ui.get("type") or "?"
    is_root = ui.get("type") == "Root"
    icon = "🔴" if is_root else "🟠"
    title = f"{icon} 콘솔 로그인 · {'ROOT' if is_root else ui.get('type','?')}"
    body = [
        f"주체 `{who}`",
        f"MFA 사용 `{mfa}`",
        f"소스 IP `{detail.get('sourceIPAddress','?')}`",
        f"결과 `{(detail.get('responseElements') or {}).get('ConsoleLogin','?')}`",
    ]
    return title, "\n".join(body), who


def _post(webhook: str, title: str, body: str, enrich: str) -> int:
    text = f"*{title}*\n{body}"
    if enrich:
        text += f"\n\n*EKS 감사로그 (±{ENRICH_WINDOW_S // 60}분)*\n{enrich}"
    req = urllib.request.Request(
        webhook,
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — 고정 https 웹훅
        return resp.status


def handler(event, _context):
    src = event.get("source", "")
    detail = event.get("detail") or {}
    when = time.time()
    enrich = ""

    if src == "aws.guardduty":
        title, body, actor = _guardduty_blocks(detail)
        enrich = _enrich(actor, when)
    elif src == "aws.signin":
        title, body, actor = _signin_blocks(detail)
        enrich = _enrich(actor, when)
    elif src == "mp.synthetic":
        # A-33 월 1회 합성 점검 — 🔴 **이 경로가 없으면 "조용함" 이 정상인지 고장인지 구분이 안 된다.**
        #    C-65 가 스스로 적은 대가("Lambda 는 단일 실패점이고 그 실패는 조용하다")를 받는 장치다.
        title = "🧪 합성 점검 (A-33)"
        body = (
            "월 1회 자동 점검입니다. 이 메시지가 **보이면** 보안 알림 경로가 살아 있습니다.\n"
            "🔴 이 메시지가 **안 오면** 경로가 죽은 것입니다 — GuardDuty·EventBridge·Lambda·웹훅 순으로 확인하세요."
        )
    else:
        # 🔵 모르는 이벤트도 버리지 않고 보낸다 — 규칙을 넓혔는데 포맷터가 없어서
        #    조용히 사라지는 것이 이 컴포넌트에서 가장 나쁜 실패다.
        title = f"ℹ️ 미분류 보안 이벤트 · `{src or 'unknown'}`"
        body = f"```{json.dumps(event, ensure_ascii=False)[:1500]}```"

    status = _post(_webhook(), title, body, enrich)
    return {"posted": status, "source": src}
