#!/usr/bin/env python3
"""fb-secrets 원본 시크릿 위생 검사 — 읽기 전용. 🔴 값은 절대 출력하지 않는다(크기·이름만).

세 가지를 한 번에 본다:

  1. 번들 크기 가드 (0-11d)
     AWS 이관 후 이 시크릿들은 SSM Parameter Store 번들 6개가 된다(C-23).
     standard tier 한도 = **4,096 B**. `app-secrets` 는 이미 3,385 B(82.6%)라
     **SA JSON 하나만 더 넣으면 초과**한다. 초과하면 PutParameter 가 실패하고,
     그 실패 모드가 "조용한 갱신 정지"다 → 넘기 **전에** 여기서 막는다.

  2. 죽은 키 (0-11c)
     어떤 ExternalSecret 도 참조하지 않는 키. SSM 으로 충실히 복제하기 전에 지운다
     — 안 그러면 죽은 키가 이관되어 영원히 산다.

  3. 빈 값 키 (0-11c 부수 발견)
     참조는 살아 있는데 값이 0 bytes 인 키. 소비 코드가 "없으면 스킵" 경로로 빠져
     **기능이 조용히 꺼져 있다**. 크기만으로 잡히는 종류라 여기서 같이 본다.

용도
    python3 check-secret-bundles.py                 # 사람이 볼 표
    python3 check-secret-bundles.py --strict        # 위반 시 exit 1 (Ansible assert·CI 가드)
    python3 check-secret-bundles.py --json          # 기계용

전제: kubectl 이 PATH 에 있고 클러스터에 닿는다(마스터에서 실행).
"""
import argparse
import base64
import json
import subprocess
import sys

SOURCE_NS = "fb-secrets"
# SSM standard tier 한도. 넘으면 advanced 로 승격되는데 **되돌릴 수 없다**(C-23 · 0-11d).
SSM_STANDARD_LIMIT = 4096
# 경보선. 한도가 아니라 여유를 남기는 선이다 — 한도에서 막으면 이미 늦다.
DEFAULT_WARN_BYTES = 3600

# `dataFrom.extract` 로 통째 소비되는 시크릿은 키 단위 참조 판정이 불가능하다 → 죽은키 검사 제외.
# (해당 시크릿은 전체가 한 덩어리로 쓰인다)


def sh(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def bundle_bytes(data: dict) -> int:
    """이 시크릿을 SSM 에 넣을 때의 JSON 번들 크기. 값은 반환하지 않는다."""
    decoded = {k: base64.b64decode(v).decode("utf-8", "replace") for k, v in data.items()}
    return len(json.dumps(decoded, separators=(",", ":")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="위반이 있으면 exit 1")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--warn-bytes", type=int, default=DEFAULT_WARN_BYTES)
    ap.add_argument("--namespace", default=SOURCE_NS)
    args = ap.parse_args()

    src = json.loads(sh("kubectl", "-n", args.namespace, "get", "secret", "-o", "json"))
    esl = json.loads(sh("kubectl", "get", "externalsecret", "-A", "-o", "json"))

    referenced: set[tuple[str, str]] = set()
    whole: set[str] = set()
    for item in esl["items"]:
        spec = item["spec"]
        for entry in spec.get("data") or []:
            ref = entry.get("remoteRef") or {}
            referenced.add((ref.get("key"), ref.get("property")))
        for entry in spec.get("dataFrom") or []:
            extract = entry.get("extract") or {}
            if extract.get("key"):
                whole.add(extract["key"])

    report: dict = {"oversize": [], "dead": [], "empty": [], "bundles": []}

    for secret in src["items"]:
        name = secret["metadata"]["name"]
        data = secret.get("data") or {}
        size = bundle_bytes(data)
        pct = size / SSM_STANDARD_LIMIT * 100
        report["bundles"].append({"secret": name, "keys": len(data), "bytes": size, "pct": round(pct, 1)})
        if size > args.warn_bytes:
            report["oversize"].append({"secret": name, "bytes": size, "limit": args.warn_bytes})

        for key, value in sorted(data.items()):
            raw_len = len(base64.b64decode(value))
            if raw_len == 0:
                report["empty"].append({"secret": name, "key": key})
            if name in whole:
                continue  # dataFrom.extract — 키 단위 판정 불가
            if (name, key) not in referenced:
                report["dead"].append({"secret": name, "key": key, "bytes": raw_len})

    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"=== 번들 크기 (SSM standard 한도 {SSM_STANDARD_LIMIT} B · 경보선 {args.warn_bytes} B) ===")
        for b in sorted(report["bundles"], key=lambda x: -x["bytes"]):
            flag = "  🔴 초과" if b["bytes"] > args.warn_bytes else ""
            print(f"  {b['secret']:<26} keys={b['keys']:<3} {b['bytes']:>5} B  ({b['pct']}%){flag}")
        print(f"\n=== 죽은 키 — 어떤 ExternalSecret 도 참조하지 않음 ({len(report['dead'])}개) ===")
        for d in report["dead"]:
            print(f"  {d['secret']}/{d['key']}  ({d['bytes']} bytes)")
        print(f"\n=== 빈 값 키 — 참조는 살아 있는데 값이 0 bytes ({len(report['empty'])}개) ===")
        for e in report["empty"]:
            print(f"  {e['secret']}/{e['key']}   ← 소비 코드가 조용히 스킵 경로로 빠진다")

    violations = len(report["oversize"])
    if args.strict and violations:
        print(f"\n🔴 번들 크기 초과 {violations}건 — SSM standard({SSM_STANDARD_LIMIT} B)를 넘기기 전에 줄여라.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
