"""ALB → Lambda 이벤트 번역 — 접수 함수(`*-api`)가 공유한다.

**FastAPI 를 얹지 않는 이유.** 접수 함수가 하는 일은 라우트 2개(POST 접수 · GET 폴링)뿐이고,
그걸 위해 ASGI 어댑터를 넣으면 콜드스타트에 프레임워크 import 가 얹힌다. 접수 함수는 타임아웃이
**10초**라(계약표) INIT 이 가장 비싼 함수다 — 여기서는 얇은 편이 맞다.
🔵 무거운 라우팅이 필요해지면 그때 어댑터를 넣는다. 지금은 경로 2개다.

🔴 **ALB 는 API Gateway 와 이벤트 모양이 다르다.** ALB 는 `path`·`httpMethod` 를 최상위에 주고
   응답에 `statusCode` 를 요구한다. API Gateway payload v2(`requestContext.http.method`)를
   가정하고 짜면 **모든 요청이 502** 가 된다 — 대상그룹이 응답 형식을 못 읽기 때문이다.
"""
from __future__ import annotations

import base64
import json
from typing import Any

JSON_HEADERS = {"Content-Type": "application/json; charset=utf-8"}


def method(event: dict) -> str:
    return (event.get("httpMethod") or "").upper()


def path(event: dict) -> str:
    return event.get("path") or ""


def body(event: dict) -> dict:
    """요청 본문 → dict. 파싱 실패는 빈 dict — 호출부가 400 으로 답한다."""
    raw = event.get("body")
    if raw is None:
        return {}
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except Exception:                     # noqa: BLE001 — 깨진 본문은 400 으로 흘린다
            return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def reply(status: int, payload: dict) -> dict:
    """ALB 가 그대로 내보낼 수 있는 형태. `statusCode` 가 없으면 502 가 된다."""
    return {
        "statusCode": status,
        "statusDescription": f"{status}",
        "headers": JSON_HEADERS,
        "isBase64Encoded": False,
        "body": json.dumps(payload, ensure_ascii=False),
    }


def error(status: int, message: str) -> dict:
    """FastAPI 의 `HTTPException` 과 **같은 본문 모양**(`{"detail": ...}`)을 유지한다 —
    프론트가 이미 그 키를 읽고 있어서, 여기서 모양을 바꾸면 에러 메시지가 화면에서 사라진다."""
    return reply(status, {"detail": message})


def tail_segment(request_path: str) -> str:
    """`/api/recipes/extract/{job_id}` → `job_id`. 빈 문자열이면 폴링이 아니다."""
    return request_path.rstrip("/").rsplit("/", 1)[-1] if request_path else ""
