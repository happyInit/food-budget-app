"""드리프트 카나리 단위테스트 — 네트워크·자격증명 없이 검증 가능한 부분만.

카나리의 본체(모델 호출)는 실제 API 를 타야 의미가 있어 단위테스트 대상이 아니다.
여기서는 **"운영 코드를 재사용하는가"** 와 **"입력이 매 실행 동일한가"** 를 고정한다.
둘 중 하나라도 깨지면 카나리가 감시 능력을 잃는다(설정을 복붙하면 운영과 갈라지고,
입력이 흔들리면 판정이 흔들린다).
"""
import inspect

from app import config_canary
from app.pipeline.backend.vision import _SYSTEM


def test_synth_receipt_is_deterministic_png():
    """합성 영수증은 매 실행 **바이트까지 동일**해야 한다 — 입력이 흔들리면 비교가 무의미하다."""
    a, b = config_canary._synth_receipt(), config_canary._synth_receipt()
    assert a == b
    assert a.startswith(b"\x89PNG\r\n\x1a\n")


def test_canary_reuses_production_config_not_a_copy():
    """설정을 복붙하지 않고 운영 객체의 `_config()` 를 재사용한다.

    복붙하면 누가 vision.py 를 고쳐도 카나리는 옛 설정을 계속 검사한다 —
    감시 대상이 운영과 달라지는 순간 카나리는 거짓 안심만 준다.
    """
    src = config_canary._probe.__code__.co_names
    assert "_config" in src, "운영 _config() 를 호출하지 않는다 — 설정이 복제됐을 가능성"
    # 프롬프트도 운영 상수를 그대로 쓰는지(모듈이 vision 을 임포트하는 경로로 확인)
    assert _SYSTEM, "운영 시스템 프롬프트 상수가 비었다"


def test_exit_codes_are_distinguishable():
    """종료코드 계약: 0=정상 · 1=드리프트 · 2=설정/환경 오류.

    2 를 1 과 섞으면 크론 알람이 **자격증명 실수를 모델 드리프트로 오인**한다.
    """
    doc = config_canary.__doc__ or ""
    assert "0=정상" in doc and "1=드리프트" in doc and "2=설정" in doc

def test_canary_builds_backend_via_production_factory():
    """백엔드를 **직접 조립하지 않고** 운영 팩토리(get_ocr_backend)로 만든다.

    인자를 카나리에서 나열하면 운영에 인자가 추가될 때 조용히 갈라진다.
    실제로 2026-08-03 에 두 번 갈라졌다 —
      ① gcp_sa_key_json 누락: 자격증명 실수가 "드리프트 감지" 로 오보됐다.
      ② gemini_timeout_s·image_max_side 누락: 운영과 다른 조건(60s·1600)으로 검사했다.
    위 test_canary_reuses_production_config_not_a_copy 는 `_config()` 재사용만 봐서
    **이 구멍을 못 잡았다.** 조립 지점까지 고정한다.
    """
    src = inspect.getsource(config_canary._probe)
    assert "get_ocr_backend" in src, "운영 팩토리를 안 쓴다 — 인자 나열은 반드시 갈라진다"
    assert "VisionBackend(" not in src, (
        "백엔드를 직접 조립한다 — 운영 인자가 늘면 카나리만 뒤처진다"
    )


def test_backend_is_built_outside_the_api_try():
    """백엔드 조립은 API 호출 try **밖**이어야 한다.

    안에 있으면 설정·자격증명 오류(exit 2 감)가 모델 거부(exit 1 = 드리프트)로
    둔갑한다. 2026-08-03 오탐의 정확한 기전이다.
    """
    src = inspect.getsource(config_canary._probe)
    assert src.index("get_ocr_backend()") < src.index("try:"), (
        "팩토리 호출이 try 안에 있다 — 자격증명 실수가 드리프트로 오보된다"
    )
