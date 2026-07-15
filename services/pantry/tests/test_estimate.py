"""순수 추정 seam — estimate_expire_date. DB·시계 무관, 리터럴로 검증(독립 소스 오브 트루스).

정책(2026-07-15 확정): 저장할 expire_at = 담은날 + days_max(추정 소비기한 상한).
days_max 가 null 이면 days_min 으로 폴백, 둘 다 null(shelf_life_ref 의 상태값 WHEN_RIPE/INDEFINITE
/NOT_RECOMMENDED 등)이면 추정 불가 → None(유저입력/무기한). '임박' 조기화는 저장값이 아니라 조회 window 담당.
"""
from __future__ import annotations

from datetime import date

from app.estimate import estimate_expire_date


def test_uses_days_max():
    # 1/1 담음, 보관수명 3~7일 → 소비기한 = 1/1 + 7일 = 1/8 (상한 채택)
    assert estimate_expire_date(date(2026, 1, 1), days_min=3, days_max=7) == date(2026, 1, 8)


def test_falls_back_to_days_min_when_max_null():
    # days_max 없으면 days_min 으로 폴백: 1/1 + 5일 = 1/6
    assert estimate_expire_date(date(2026, 1, 1), days_min=5, days_max=None) == date(2026, 1, 6)


def test_none_when_both_null():
    # 상태값(WHEN_RIPE/INDEFINITE 등)으로 days 가 비면 추정 불가 → None
    assert estimate_expire_date(date(2026, 1, 1), days_min=None, days_max=None) is None


def test_month_rollover():
    # 월 경계 산술 sanity: 1/31 + 1일 = 2/1 (days_max 채택)
    assert estimate_expire_date(date(2026, 1, 31), days_min=None, days_max=1) == date(2026, 2, 1)
