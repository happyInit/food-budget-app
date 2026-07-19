"""account 서비스 제외재료 API 클라이언트 — 양방향 개인화 통합.

챗봇 세션 비선호 ↔ 마이 페이지 영속 제외재료(`account.user_excluded_item`)를 잇는다.
**남의 서비스 테이블을 직접 안 건드리고 API만 호출**(CONVENTIONS: 크로스-서비스=API).

⚠️ **기본 OFF** (`account_integration_enabled=False`). account API가 JWT 소유자 스코프라
   챗봇에 **인증(JWT)이 생겨야** 동작한다. 미인증·미설정·장애면 전부 **무동작**(빈 결과) →
   현재 세션-스코프 개인화와 완전 동일하게 유지(비침습).
"""
from __future__ import annotations

import httpx

from app.config import settings

# account 라우터 prefix 는 /api/users (services/account/app/routers.py) — /api 누락 시 404 → 조용히 무동작.
_ENDPOINT = "/api/users/excluded-items"


def _active(token: str | None) -> bool:
    return bool(settings.account_integration_enabled and settings.account_base_url and token)


def _headers(token: str) -> dict:
    return {"Authorization": token}


async def get_excluded_item_ids(token: str | None) -> list[int]:
    """마이 페이지 제외재료 item_id 목록(read). 비활성·장애면 빈 리스트."""
    if not _active(token):
        return []
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(settings.account_base_url + _ENDPOINT, headers=_headers(token))
            r.raise_for_status()
            return [int(x["item_id"]) for x in r.json() if x.get("item_id") is not None]
    except Exception:
        return []


async def add_excluded_items(token: str | None, items: list[tuple[int, str]]) -> None:
    """챗봇 비선호를 마이 페이지에 영속(write). 비활성·장애면 무동작. 개별 실패는 무시."""
    if not _active(token) or not items:
        return
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            for item_id, name in items:
                try:
                    await c.post(settings.account_base_url + _ENDPOINT, headers=_headers(token),
                                 json={"item_id": item_id, "name": name})
                except Exception:
                    continue
    except Exception:
        return
