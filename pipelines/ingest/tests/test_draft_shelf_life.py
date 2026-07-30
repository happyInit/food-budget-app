"""소비기한 AI 초안 — 식품안전 방어선 검증.

소비기한을 **길게** 잡으면 유저가 상한 음식을 먹는다. 모델이 과대 추정해도 코드가 막아야 한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from draft_shelf_life import _MAX_DAYS, rows_from_draft  # noqa: E402


def _rows(draft):
    return {r["storage"]: r for r in rows_from_draft(1, "두부", "가공식품", draft)}


def test_caps_overlong_estimate():
    """모델이 냉장 999일을 주장해도 상한(60일)을 넘겨 저장하지 않는다."""
    got = _rows({"FRIDGE": {"min": 2, "max": 999}})
    assert got["FRIDGE"]["dmax"] == _MAX_DAYS["FRIDGE"] == 60


def test_min_never_exceeds_capped_max():
    """상한에 걸려 max가 줄면 min도 함께 줄어야 한다 — min>max 는 모순이다."""
    got = _rows({"ROOM": {"min": 900, "max": 999}})
    assert got["ROOM"]["dmin"] <= got["ROOM"]["dmax"] == _MAX_DAYS["ROOM"]


def test_null_storage_is_skipped_not_guessed():
    """부적절한 보관(생선의 ROOM)은 null 로 오고, 그 보관은 저장하지 않는다."""
    got = _rows({"ROOM": None, "FRIDGE": {"min": 2, "max": 3}})
    assert "ROOM" not in got and got["FRIDGE"]["dmax"] == 3


def test_invalid_max_is_skipped():
    """상한이 없거나 0 이하면 그 보관은 버린다 — 추정해서 채우지 않는다."""
    assert _rows({"FRIDGE": {"min": 2, "max": 0}}) == {}
    assert _rows({"FRIDGE": {"min": 2, "max": "사흘"}}) == {}


def test_bad_min_is_dropped_not_the_row():
    """min 이 이상하면 min 만 비우고 max 는 살린다(정보를 통째로 버리지 않는다)."""
    got = _rows({"FRIDGE": {"min": 99, "max": 3}})
    assert got["FRIDGE"]["dmin"] is None and got["FRIDGE"]["dmax"] == 3


def test_empty_draft_yields_nothing():
    assert rows_from_draft(1, "두부", None, {}) == []


# ── 대상 축소 회귀 (실측 2026-07-29) ────────────────────────────────────────
def test_freezer_excluded_from_ai_drafts():
    """모델이 냉동에 일괄 '6~12일'을 반환한다(삼치·황태·호두 실측) — 냉동은 수개월인데
    12일을 붙이면 멀쩡한 식재료가 임박 알림으로 떠서 유저가 버린다."""
    from draft_shelf_life import _STORAGES

    assert "FREEZER" not in _STORAGES
    got = _rows({"FRIDGE": {"min": 1, "max": 2}, "FREEZER": {"min": 6, "max": 12}})
    assert set(got) == {"FRIDGE"}


def test_fresh_categories_exclude_shelf_stable():
    """상비양념·곡류·견과는 수작업 큐레이션 대상 — AI 가 크게 틀리는 구간이다."""
    from draft_shelf_life import _FRESH_CATEGORIES

    for c in ("양념", "유지", "곡류", "견과", "허브", "가공식품"):
        assert c not in _FRESH_CATEGORIES, c
    for c in ("채소", "과일", "수산물", "육류"):
        assert c in _FRESH_CATEGORIES, c


def test_dried_pattern_catches_shelf_stable_seafood():
    """황태·북어는 '수산물'이지만 상온 장기 보관 — 분류만으로는 못 거른다."""
    import re

    from draft_shelf_life import _DRIED_PATTERN

    for n in ("황태", "북어", "무말랭이", "건새우", "말린표고"):
        assert re.search(_DRIED_PATTERN, n), n
    for n in ("삼치", "장어", "소라"):
        assert not re.search(_DRIED_PATTERN, n), n
