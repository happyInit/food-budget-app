"""최저가 이상탐지 z-score 로직 — DB 없이 순수 함수 검증.

실데이터 캘리브레이션 근거는 `detect_price_anomaly.py` 독스트링 참조.
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from detect_price_anomaly import detect  # noqa: E402


def _rows(prices, item_id=1, name="고구마", source="kurly", disc=None, weight_g=500):
    """[100g 단가…] → SQL 결과 형태.

    (item_id, name, source, date, 단가, 할인율, 상품id, 실제가, 관측시점)
    뒤 3개는 **근거 스냅샷**이다 — price_anomaly 가 NOT NULL 로 요구한다(합성금액 금지).
    실제가는 100g 단가에서 역산해 일관되게 만든다.
    """
    d0 = date(2026, 7, 1)
    return [(item_id, name, source, d0 + timedelta(days=i), p, disc,
             1000 + item_id, round(p * weight_g / 100, 2),
             datetime(2026, 7, 1, 9, 0) + timedelta(days=i))
            for i, p in enumerate(prices)]


def test_detects_real_drop():
    """평균에서 크게 벗어난 급락은 잡는다."""
    got = detect(_rows([500, 505, 495, 510, 490, 500, 508, 492] + [400]))
    assert len(got) == 1
    a = got[0]
    assert a.item_id == 1 and a.source == "kurly"
    assert a.drop_pct == pytest.approx(20.0, abs=0.5)
    assert a.z_score < -2
    assert a.is_record_low is True


def test_ignores_small_drop_even_with_extreme_z():
    """σ가 극소해 z는 크지만 체감 없는 하락은 제외한다.

    실측에서 item=95가 z=-16.95인데 실제 하락은 -7%뿐이었다 — 이 케이스의 회귀 방지.
    """
    prices = [1000, 1001, 999, 1000, 1002, 998, 1000, 1001]   # σ≈1
    got = detect(prices and _rows(prices + [930]))            # -7% 하락
    assert got == []                                          # z는 극단이지만 drop < 8%


def test_ignores_rise():
    """가격 상승은 이상탐지 대상이 아니다."""
    assert detect(_rows([500, 505, 495, 510, 490, 500, 508, 492] + [700])) == []


def test_skips_when_too_few_samples():
    """baseline 표본이 부족하면 판정하지 않는다(오탐 방지)."""
    assert detect(_rows([500, 490, 510, 400])) == []          # N=3 < 7


def test_skips_zero_variance():
    """변동이 전혀 없으면 z가 정의되지 않으므로 스킵한다."""
    assert detect(_rows([500] * 8 + [500])) == []


def test_series_are_separated_by_item_and_source():
    """품목·소스별로 독립 판정한다(컬리 급락이 오아시스에 섞이면 안 됨)."""
    rows = _rows([500, 505, 495, 510, 490, 500, 508, 492] + [400], item_id=1, source="kurly")
    rows += _rows([500, 505, 495, 510, 490, 500, 508, 492] + [500], item_id=1, source="oasis")   # 급락 없음
    rows += _rows([300, 303, 297, 305, 295, 300, 304, 296] + [290], item_id=2, name="감자")  # -3%, 미달
    got = detect(rows)
    assert [(a.item_id, a.source) for a in got] == [(1, "kurly")]


def test_sorted_by_felt_drop_not_z():
    """체감(하락률) 큰 순으로 정렬한다 — z 순이면 σ 작은 품목이 상위를 차지한다."""
    rows = _rows([500, 505, 495, 510, 490, 500, 508, 492] + [400], item_id=1, name="A")            # -20%
    rows += _rows([1000, 1002, 998, 1001, 999, 1000, 1002, 998] + [880],
                  item_id=2, name="B")                             # -12%, z는 더 큼
    got = detect(rows)
    assert [a.canonical_name for a in got] == ["A", "B"]


def test_record_low_flag():
    """윈도우 내 최저 갱신 여부를 표시한다."""
    a = detect(_rows([500, 480, 520, 500, 510, 490, 505, 500] + [450]))[0]
    assert a.is_record_low is True
    b = detect(_rows([500, 380, 520, 500, 510, 490, 505, 500] + [400]))[0]
    assert b.is_record_low is False        # 과거 380이 더 낮음


def test_threshold_is_tunable():
    """임계는 파라미터로 조절 가능해야 한다(이력이 쌓이면 조인다)."""
    rows = _rows([500, 505, 495, 510, 490, 500, 508, 492] + [460])                     # -8%
    assert detect(rows, min_drop_pct=8.0) != []
    assert detect(rows, min_drop_pct=15.0) == []


def test_top_n_caps_and_keeps_biggest_drops():
    """노출 정책 ① — 조건 충족이 많으면 체감 순 상위 N건만 채택한다."""
    rows = []
    for i in range(30):                       # 하락률이 서로 다른 30개 시계열
        drop = 10 + i                         # 10%~39%
        base = [1000, 1010, 990, 1020, 980, 1000, 1015, 985]
        rows += _rows(base + [int(1000 * (1 - drop / 100))], item_id=i + 1, name=f"품목{i}")
    assert len(detect(rows, top_n=None)) == 30          # 무제한이면 전부
    got = detect(rows, top_n=20)
    assert len(got) == 20                                # 상한 적용
    assert got[0].drop_pct > got[-1].drop_pct            # 체감 순
    assert got[0].canonical_name == "품목29"             # 가장 큰 하락이 1위


def test_top_n_noop_when_under_limit():
    """상한 미만이면 자르지 않는다(평상시엔 안전판일 뿐)."""
    rows = _rows([500, 505, 495, 510, 490, 500, 508, 492] + [400])
    assert len(detect(rows, top_n=20)) == 1


# ── 성숙도 게이트 (실측 회귀 2026-07-29) ────────────────────────────────────
def test_mature_samples_constant_matches_spec():
    """ai-spec §2=30일 이동평균 · §4.1='4주 미만 오탐↑' → 발행 임계는 4주(28일)."""
    from detect_price_anomaly import MATURE_SAMPLES

    assert MATURE_SAMPLES == 28


def test_immature_baseline_still_detected_but_flagged_by_samples():
    """미성숙 기준선도 **탐지·기록은 된다** — 막는 것은 발행뿐이다.

    실측(2026-07-29): 가격 이력이 07-13에 시작해 최대 15일이고 컬리는 7일 연속 결손으로
    9일뿐이었다. 그 상태로 탐지된 7건 중 6건이 N=8인 컬리였다 — 가장 미성숙한 소스에서
    알림이 나갈 뻔했다. 기록은 오탐 분석에 필요하므로 남기고, 발행만 게이트한다.
    """
    from detect_price_anomaly import MATURE_SAMPLES

    got = detect(_rows([500, 505, 495, 510, 490, 500, 508, 492] + [400]))
    assert len(got) == 1
    assert got[0].samples == 8               # 탐지는 된다
    assert got[0].samples < MATURE_SAMPLES   # 그러나 발행 대상은 아니다


def test_mature_baseline_passes_gate():
    """표본이 28일을 넘으면 게이트를 통과한다 — 이력이 쌓이면 자동으로 풀린다."""
    from detect_price_anomaly import MATURE_SAMPLES

    prices = [500, 505, 495, 510, 490, 500, 508, 492] * 4      # 32일
    got = detect(_rows(prices + [400]))
    assert len(got) == 1
    assert got[0].samples >= MATURE_SAMPLES
