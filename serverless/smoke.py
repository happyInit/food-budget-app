"""배포 직후 11종을 한 번에 확인한다 — *"올렸는데 도는지 모르는"* 구간을 없앤다.

🔴 **이 스크립트가 필요한 이유** = Lambda 의 실패는 대부분 **첫 호출에서만** 드러난다.
   `terraform apply` 는 성공하고, 콘솔에는 함수가 초록으로 보이고, 그런데 부르면
   `ModuleNotFoundError` 나 `invalid ELF header` 로 죽는다. 오늘 하루 쫓은 결함이 전부
   그 부류였다(끊어진 심볼릭 링크 · 마커 때문에 빠진 의존성 · 진입점 이름 충돌).
   ⇒ 배포 다음 순서는 «눌러 보기» 가 아니라 **이 스크립트**여야 한다.

🔵 **안전하다 — 기본은 전부 미리보기다.**
   배치 5종은 `{"apply": false}` 로 부른다(적재 0). 접수 2종은 **폴링 경로만** 두드리고
   실제 잡을 만들지 않는다. `--write` 를 줘야 쓰기가 있는 경로를 태운다.

사용:
    python serverless/smoke.py                    # 전체(읽기 전용)
    python serverless/smoke.py --only chat-api    # 하나만
    python serverless/smoke.py --write            # 🔴 실제 적재·잡 생성까지
    python serverless/smoke.py --region ap-northeast-2 --profile mp-ai
"""
from __future__ import annotations

import argparse
import json
import sys
import time

PREFIX = "mp-ai-"

# ── 무엇을 어떻게 두드리나 ────────────────────────────────────────────────────
# `kind` 가 검증 방식을 정한다:
#   batch  — 미리보기로 Invoke. 요약 dict 가 오면 성공(적재 0)
#   alb    — ALB 이벤트를 만들어 Invoke. `statusCode` 가 나와야 한다
#            🔴 API GW v2 와 다르다 — ALB 는 statusCode 가 없으면 502 를 준다
#   sqs    — 🔵 **직접 안 부른다.** 워커는 큐가 깨우는 것이고, 손으로 부르면
#            «큐 배선이 틀렸는데 워커는 멀쩡» 한 상태를 통과시킨다. 대신 접수를 통해
#            흘려보내고(`--write`) 잡 상태가 끝나는지로 본다.
FUNCTIONS = {
    "shelflife-draft": {"kind": "batch", "payload": {"limit": 1, "apply": False}},
    "ner-backfill":    {"kind": "batch", "payload": {"limit": 1, "apply": False}},
    "price-detect":    {"kind": "batch", "payload": {"apply": False}},
    "sentiment-batch": {"kind": "batch", "payload": {"limit": 1, "apply": False}},
    "summarize-batch": {"kind": "batch", "payload": {"limit": 1, "apply": False}},
    "video-api":       {"kind": "alb", "method": "GET", "path": "/api/recipes/extract/없는잡",
                        "expect": 404},
    "ocr-api":         {"kind": "alb", "method": "GET", "path": "/api/pantry/ocr/없는잡",
                        "expect": 404},
    "chat-api":        {"kind": "alb", "method": "GET", "path": "/health", "expect": 200},
    "video-worker":    {"kind": "sqs"},
    "ocr-worker":      {"kind": "sqs"},
}


def alb_event(method: str, path: str) -> dict:
    """🔴 `requestContext.elb` 가 **반드시** 있어야 한다 — Mangum 과 우리 `common/alb.py` 가
    둘 다 그 키로 ALB 를 판정한다. 콘솔 Test 버튼의 기본 payload 로는 재현이 안 된다."""
    return {
        "requestContext": {"elb": {"targetGroupArn": "arn:aws:elasticloadbalancing:smoke"}},
        "httpMethod": method, "path": path, "queryStringParameters": {},
        "headers": {"host": "smoke.local", "user-agent": "mp-smoke/1"},
        "body": "", "isBase64Encoded": False,
    }


def invoke(client, name: str, payload: dict) -> tuple[bool, str]:
    try:
        r = client.invoke(FunctionName=PREFIX + name, InvocationType="RequestResponse",
                          Payload=json.dumps(payload).encode())
    except Exception as exc:                      # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:120]}"

    body = r["Payload"].read().decode("utf-8", "replace")
    # 🔴 `FunctionError` 를 안 보면 **예외를 성공으로 읽는다.** Lambda 는 함수가 죽어도
    #    HTTP 200 을 준다 — 실패는 이 헤더에만 있다. 우리가 오늘 쫓은 «조용한 실패» 와 같은 모양이다.
    if r.get("FunctionError"):
        try:
            err = json.loads(body)
            return False, f"{err.get('errorType')}: {str(err.get('errorMessage'))[:140]}"
        except json.JSONDecodeError:
            return False, body[:160]
    return True, body


def check(client, name: str, spec: dict, write: bool) -> tuple[str, str]:
    kind = spec["kind"]

    if kind == "sqs":
        # 🔵 직접 부르지 않는다(머리말 참조). 배선만 확인한다.
        try:
            cfg = client.get_function(FunctionName=PREFIX + name)
            arch = ",".join(cfg["Configuration"].get("Architectures", []))
            # 🔴 arm64 가 아니면 첫 호출에서 invalid ELF header 로 죽는다(C-29 · 번들이 aarch64 휠).
            ok = arch == "arm64"
            return ("✅" if ok else "🔴"), f"배선만 확인 · arch={arch or '?'}"
        except Exception as exc:                  # noqa: BLE001
            return "🔴", f"{type(exc).__name__}: {str(exc)[:120]}"

    if kind == "batch":
        payload = dict(spec["payload"])
        if write:
            payload["apply"] = True
        ok, body = invoke(client, name, payload)
        if not ok:
            return "🔴", body
        # 🔵 «미리보기였나 실제였나» 를 결과에 남긴다 — CloudTrail 은 payload 를 기록하지 않는다.
        return "✅", f"apply={payload['apply']} · {body[:110]}"

    # alb
    ok, body = invoke(client, name, alb_event(spec["method"], spec["path"]))
    if not ok:
        return "🔴", body
    try:
        resp = json.loads(body)
    except json.JSONDecodeError:
        return "🔴", f"JSON 이 아니다: {body[:120]}"
    if "statusCode" not in resp:
        # 🔴 이게 빠지면 ALB 가 502 를 준다. 함수는 «성공» 이라 로그만 봐서는 안 보인다.
        return "🔴", f"statusCode 가 없다(ALB 는 502 를 준다) — {body[:110]}"
    got = resp["statusCode"]
    if got != spec["expect"]:
        return "🔴", f"statusCode={got}, 기대={spec['expect']} · {str(resp.get('body'))[:90]}"
    return "✅", f"statusCode={got} · {str(resp.get('body'))[:100]}"


def main() -> int:
    ap = argparse.ArgumentParser(description="배포된 AI Lambda 11종 스모크")
    ap.add_argument("--region", default="ap-northeast-2")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--only", action="append", help="함수 이름(prefix 없이). 여러 번 줄 수 있다")
    ap.add_argument("--write", action="store_true",
                    help="🔴 실제 적재까지 태운다(기본은 미리보기)")
    args = ap.parse_args()

    try:
        import boto3
    except ImportError:
        print("🔴 boto3 가 없다 — `pip install boto3`")
        return 2

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    client = session.client("lambda")

    targets = {k: v for k, v in FUNCTIONS.items() if not args.only or k in args.only}
    if not targets:
        print(f"🔴 그런 함수가 없다: {args.only}")
        return 2

    # 🔵 **배포된 것부터 센다.** 없는 함수를 «실패» 로 세면, 아직 안 올린 것과 올렸는데
    #    깨진 것이 한 덩어리로 보여서 진단이 흐려진다. 둘을 가른다.
    deployed = set()
    paginator = client.get_paginator("list_functions")
    for page in paginator.paginate():
        deployed |= {f["FunctionName"] for f in page["Functions"]}

    print(f"▶ 스모크 · region={args.region} · write={args.write}")
    if args.write:
        print("  🔴 --write 다 — 실제 적재·잡 생성이 일어난다")
    print()

    bad = 0
    missing = []
    for name, spec in targets.items():
        if PREFIX + name not in deployed:
            missing.append(name)
            continue
        t0 = time.perf_counter()
        mark, detail = check(client, name, spec, args.write)
        ms = (time.perf_counter() - t0) * 1000
        if mark == "🔴":
            bad += 1
        print(f"  {mark} {name:16} {ms:7.0f}ms  {detail}")

    if missing:
        print(f"\n  ⏸ 아직 배포 안 됨 {len(missing)}종 — {', '.join(missing)}")
        print("     (선행이 남았을 수 있다: 권한 · 내부 NLB · SQS/S3 — docs/serverless/06)")

    print(f"\n{'🔴' if bad else '✅'} 배포된 {len(targets) - len(missing)}종 중 실패 {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
