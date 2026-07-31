"""상품명 → volume_ml 파싱 (#286).

`retail_product.volume_ml` 이 0% 라, `retail_unit_price` 뷰가 조회 때마다 **상품명을 SQL
정규식으로** 파싱해 부피 단가를 냈다. 그 구조가 2026-07-23 장애를 만들었다 —
`"솔리몬 스퀴즈드 레몬즙 1,000ml"` 에서 정규식이 콤마를 몰라 `000` 을 잡고 0 으로 나눠
뷰 REFRESH 가 통째로 죽었다(4,634행 중 1행이 가격 갱신 전체를 멈춰 세웠다).

🔴 **터지는 실패보다 안 터지는 실패가 위험하다.** `1,500ml` 을 `500` 으로 읽으면 예외 없이
   단가가 3배 부풀려진 채 서빙된다. 그래서 파서 규칙은 "모르면 None" 이고, 아래 케이스는
   전부 **운영 상품명 실물**에서 뽑았다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_norm import parse_volume_ml  # noqa: E402


@pytest.mark.parametrize("name,expect", [
    ("[8잔 분량] 오늘의일상 자몽에이드 원액 (400mL)", 400),
    ("오아시스 참치액 (500ml)", 500),
    ("불로동 주유소 참기름 (100ml)", 100),
    ("고소한 순수콩물(1L)", 1000),
    ("국산원유로 만든 무가당 플레인 요거트(1.8L)", 1800),
])
def test_single_pack(name, expect):
    assert parse_volume_ml(name) == expect


@pytest.mark.parametrize("name,expect", [
    # 🔴 묶음은 **곱한다** — 가격이 묶음 전체 기준이라 65 로 두면 100ml 단가가 20배 부푼다.
    ("야쿠르트 오리지널(65ml×20개)", 1300),
    ("메치니코프 무가당플레인(140mlx4)", 560),
    ("[특가] 6년근 순한홍삼(80ml x 60포)", 4800),
    ("[10% 할인] 백미당 유기농 우유(200ml*4입)", 800),
    ("임실치즈마을 프로바이오 요거트 </br>(120mlX3개, 플레인)", 360),
    ("[박스] 빅토리아 레몬 스파클링 (500ml x 20개)", 10000),
])
def test_multipack_is_multiplied(name, expect):
    assert parse_volume_ml(name) == expect


def test_thousand_separator_the_20260723_outage():
    """장애 당사 상품 — 콤마를 못 읽으면 `000` 이 되고 0 으로 나눠 뷰가 죽는다."""
    assert parse_volume_ml("솔리몬 스퀴즈드 레몬즙 1,000ml") == 1000


def test_first_match_wins_over_promo_clause():
    """증정 문구에 다른 부피가 섞인다 — 본품은 앞에 온다. 전부 모으면 틀린다."""
    name = "[요철&좁쌀케어] 잇퓨 리페어 테라피 순율 크림 50ml (구매 시 순율크림 1ml*2개 증정)"
    assert parse_volume_ml(name) == 50


@pytest.mark.parametrize("name", [
    # 🔴 농산물 크기 등급 — S/M/L/2L/3L. 2kg 짜리 감귤이 2리터 음료가 되면 안 된다(실측 거짓양성).
    "Ai선별 제주 하우스감귤 2kg(L-2L)",
    "무농약 유명산지 생 블루베리 (200g/L사이즈)",
    "[KF365] 무항생제 달걀 2XL(왕란) 30구(15구 *2ea)",
    "[Kurly's] 동물복지 유정란 2XL(왕란) 15구",
    # 부피가 아예 없는 것들
    "[KF365] LA 갈비 500g (냉동)",
    "무항생제 닭가슴살 500g",
    "삼성 LED 스탠드",
])
def test_not_a_volume(name):
    assert parse_volume_ml(name) is None


@pytest.mark.parametrize("name", ["이상한상품 0ml", "초대형 900L 냉장고"])
def test_out_of_range_is_none(name):
    """0 이거나 비현실적이면 **추측하지 않는다** — NULL 은 단가가 안 나올 뿐이지만,
    틀린 숫자는 조용히 잘못된 가격을 판다."""
    assert parse_volume_ml(name) is None


def test_empty_input():
    assert parse_volume_ml("") is None
    assert parse_volume_ml(None) is None
