"""pantry 서비스 냉장고 재고 조회 — 챗봇 "냉장고 재료로 추천" 위임.

챗이 pantry API(`GET /api/pantry/items`)를 JWT로 호출해 사용자 냉장고 재고의 표준품목(item_id)을
가져온다. **남의 서비스 테이블 직접접근 금지, API만**(CONVENTIONS: 크로스-서비스=API). mealplan이
이미 같은 pantry seam으로 재고를 읽어 추천에 반영하듯, 챗도 동일 seam을 재사용한다.

⚠️ **기본 OFF**(`chat_pantry_enabled=False`). pantry API가 JWT 소유자 스코프라 챗봇에 인증(JWT)이
   있어야 동작한다. 미설정·미인증·장애·빈냉장고면 전부 **무동작**(빈 결과) → 기존 되묻기 폴백과
   동일하게 degrade(비침습). account_client.py 패턴과 동형.
"""
from __future__ import annotations

import httpx

from app.config import settings

_ITEMS_ENDPOINT = "/api/pantry/items"   # pantry 라우터 prefix (services/pantry/app/routers.py)


def _active(token: str | None) -> bool:
    # JWT 전제라 account_integration_enabled(인증 존재)까지 함께 확인 — pantry는 그 위 opt-in.
    return bool(
        settings.chat_pantry_enabled
        and settings.account_integration_enabled
        and settings.pantry_base_url
        and token
    )


def _headers(token: str) -> dict:
    return {"Authorization": token}


async def get_pantry_items(token: str | None) -> list[tuple[int, str]]:
    """냉장고 재고 (item_id, name) 목록. 비활성·미인증·장애면 빈 리스트.
    item_id 없는 행(표준품목 미앵커)은 검색에 못 쓰므로 제외."""
    if not _active(token):
        return []
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(settings.pantry_base_url + _ITEMS_ENDPOINT, headers=_headers(token))
            r.raise_for_status()
            out: list[tuple[int, str]] = []
            seen: set[int] = set()
            for x in r.json():
                iid = x.get("item_id")
                if iid is None:
                    continue
                iid = int(iid)
                if iid in seen:      # 같은 품목 여러 칸(냉장/냉동)일 수 있어 중복 제거
                    continue
                seen.add(iid)
                out.append((iid, x.get("name") or ""))
            return out
    except Exception:   # noqa: BLE001 — 장애/타임아웃/포맷오류 전부 무동작(빈 결과)로 degrade
        return []
