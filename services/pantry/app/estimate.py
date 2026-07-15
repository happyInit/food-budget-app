"""소비기한 추정 — 순수 함수(딥 모듈). DB 조회(shelf_life_ref)는 호출측(queries)이 하고,
여기선 값만 받아 날짜를 계산한다 → 시계·DB 무관하게 인터페이스로 검증(tests/test_estimate.py).

정책: 담은날 + days_max(추정 소비기한 상한). days_max 없으면 days_min 폴백,
둘 다 없으면 추정 불가(None) → pantry_item.expire_at 은 null(유저입력/무기한)로 남는다.
"""
from __future__ import annotations

from datetime import date, timedelta


def estimate_expire_date(
    added: date, days_min: int | None, days_max: int | None
) -> date | None:
    days = days_max if days_max is not None else days_min
    if days is None:
        return None
    return added + timedelta(days=days)
