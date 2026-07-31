"""재고 소비기한 재계산 — **안전규칙이 SQL 에서 사라지지 않게 못박는다**.

이 스크립트는 유저에게 보이는 날짜를 자동으로 바꾸고 임박 알림에 직결된다. 로직 대부분이
SQL 이라 단위테스트로 값을 검증할 수는 없지만, **규칙이 빠지면 즉시 사고**이므로 조건의 존재를
고정한다. 실제 동작은 운영 PG 대조로 검증했다(아래 수치).
"""
import re
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / "recompute_pantry_expire.py").read_text()
_TARGETS = re.search(r'_TARGETS = """(.*?)"""', _SRC, re.S).group(1)
_UPDATE = re.search(r'_UPDATE = """(.*?)"""', _SRC, re.S).group(1)


def test_only_touches_null_expire():
    """안전규칙 1 — 이미 값이 있는 행은 **유저가 본 날짜**다(유저 입력일 수도 있다).

    이 조건이 빠지면 기존 날짜를 전부 덮어써 "8월 5일"이 갑자기 "7월 25일"이 된다.
    """
    assert "p.expire_at IS NULL" in _TARGETS
    # UPDATE 에도 다시 건다 — 조회와 갱신 사이에 유저가 값을 넣었을 수 있다(경쟁 방어)
    assert "expire_at IS NULL" in _UPDATE


def test_only_fills_future_dates():
    """안전규칙 2 — 결과가 **미래인 것만** 채운다.

    실측(2026-07-30): 채울 수 있는 2건이 전부 이미 지난 날짜가 된다. 그대로 넣으면
    "기한 없음"이던 재고가 "지남"으로 바뀌어 임박 목록(`expire_at <= current_date + 7` —
    **과거도 잡는다**)에 들어가 26 → 28 이 된다. 정보로는 정확하나 **행동 가능성이 없고**
    알림 신뢰만 깎는다. NULL 은 "모름"이라는 정직한 상태다(팀 결정: 모르면 표시하지 않음).
    """
    assert "> CURRENT_DATE" in _TARGETS


def test_joins_on_item_and_storage_combination():
    """🔴 조인 키는 **(item_id, storage) 조합**이어야 한다.

    `item_id` 만 보면 "ROOM 만 있는 감자"가 커버됨으로 잡혀 **FRIDGE 재고가 영영 안 채워진다**
    — 2026-07-29 에 실제로 낸 사고이고, 그 잘못된 가정 위에 마이그레이션 4개를 다시 썼다.
    """
    assert "x.item_id = p.item_id AND x.storage = p.storage" in _TARGETS


def test_curated_wins_over_ai_draft():
    """검수본(CURATED)이 AI 초안에 덮이지 않아야 한다 — `lookup_shelf_life` 와 같은 우선순위."""
    assert "'CURATED' THEN 0" in _TARGETS
    assert "'FOODKEEPER' THEN 1" in _TARGETS


def test_days_max_first_matches_estimate_policy():
    """정책이 `services/pantry` 의 `estimate_expire_date` 와 같아야 한다 — days_max 우선.

    두 곳이 갈리면 등록 시점 값과 재계산 값이 달라져 **같은 재료가 경로에 따라 다른 날짜**를 갖는다.

    ⚠️ 여기서 그 함수를 임포트하지 않는다 — 파이프라인 테스트가 다른 서비스 패키지에 의존하면
       운영(서비스별 venv·이미지 분리)과 어긋난다. 대신 **같은 정책 문구를 양쪽에서 고정**한다:
         · 이 테스트  = 재계산 SQL 의 COALESCE 순서
         · 서비스 쪽  = `services/pantry/tests/test_estimate.py`
       한쪽만 바뀌면 다른 쪽 테스트가 깨져 불일치가 드러난다.
    """
    assert "COALESCE(s.days_max, s.days_min)" in _TARGETS
    # 순서가 뒤집히면(min 우선) 등록 시점보다 짧은 기한이 나와 임박 알림이 앞당겨진다
    assert "COALESCE(s.days_min, s.days_max)" not in _TARGETS


def test_active_only():
    """소비·폐기된 재고는 건드리지 않는다."""
    assert "p.status = 'ACTIVE'" in _TARGETS
