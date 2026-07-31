"""재료명 → 표준품목코드(item_id) 정규화.

추출된 재료가 `item_id`를 못 얻으면 결과가 **앱 기능과 단절**된다 — 재료비 합산·냉장고 재고
매칭·최저가 알림이 전부 item_id로 동작하기 때문이다. 그래서 이 배선은 선택이 아니라 필수다.

chat 서비스(`app/main.py:_load_matcher`)와 **같은 gazetteer·같은 matcher**를 쓴다.
서비스마다 매칭 규칙이 갈리면 "챗이 인식한 재료를 영상 추출은 못 잡는" 불일치가 생긴다.
"""
from __future__ import annotations

import logging

import psycopg

from app.config import settings

log = logging.getLogger("video.normalize")


def load_item_resolver() -> tuple[callable, int]:
    """gazetteer를 1회 로드해 `name -> item_id` 함수를 만든다.

    반환: (resolver, 사전 표면형 수). DB 실패 시 (None, 0) — 추출 자체는 계속 동작해야 하므로
    정규화 없이 진행한다(item_id=None). 서비스 기동을 막지는 않는다.
    """
    from pipelines.ingest.gazetteer import load_gazetteer, load_meat_canons, make_matcher

    conninfo = (
        f"host={settings.pghost} port={settings.pgport} "
        f"dbname={settings.pgdatabase} user={settings.pguser} password={settings.pgpassword}"
    )
    with psycopg.connect(conninfo, connect_timeout=8) as conn, conn.cursor() as cur:
        gaz = load_gazetteer(cur)
        meat_canons = load_meat_canons(cur)   # 종세분화 가드(정책2) — 챗과 동일 규칙
    match = make_matcher(gaz, meat_canons)

    def resolve(name: str) -> int | None:
        """`match()`는 (item_id, canonical, method)를 준다 — 여기선 item_id만 쓴다."""
        item_id, _canon, _method = match(name or "")
        return item_id

    return resolve, len(gaz)
