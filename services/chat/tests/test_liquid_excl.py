"""육수/물 재료비 제외 판정 — 사먹는 재료(다시마·사골·국물용멸치) 오탐 회귀 방지.

is_liquid_excl 정본 = pipelines/ingest/quantity.py (vendor 심링크로 챗·recipe 공용).
"""
from app.vendor.quantity import is_liquid_excl


def test_excludes_real_broths_and_water():
    for name in ("멸치육수", "코인육수", "사골육수", "치킨스톡", "김치국물",
                 "다시마육수", "멸치다시마육수", "채수", "물", "생수", "얼음물"):
        assert is_liquid_excl(name), f"제외되어야: {name}"


def test_keeps_purchasable_ingredients():
    # 다시마(켈프)·사골(뼈)·국물용멸치·다시다 = 사먹는 재료 → 제외하면 과소계상
    for name in ("다시마", "자른 다시마", "조각다시마", "사골", "국물용멸치",
                 "국물용 멸치", "다시멸치", "다시다", "소고기", "고추장", "대파"):
        assert not is_liquid_excl(name), f"제외되면 안 됨: {name}"
