"""공통 이식 계층 테스트 — **AWS 없이** 도는 것만 담는다.

여기서 지키려는 것은 두 가지다.
① `"true"` 문자열이 실제 적재로 둔갑하지 않는가 (식품안전 배치의 승인 게이트)
② 시간이 없을 때 **잘리는 대신 자진 중단**하는가
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.runtime import event_args, logger, time_guard  # noqa: E402


class FakeContext:
    """Lambda `context` 흉내 — 남은 시간만 있으면 된다."""

    def __init__(self, remaining_ms):
        self._left = remaining_ms
        self.aws_request_id = "test-req-1"

    def get_remaining_time_in_millis(self):
        return self._left


# ── event_args ──────────────────────────────────────────────────────────────
def test_인자를_타입대로_꺼낸다():
    assert event_args({"limit": 5, "apply": True}, {"limit": int, "apply": bool}) == {
        "limit": 5, "apply": True}


def test_문자열_true_가_참으로_바뀐다():
    """🔴 이걸 안 막으면 콘솔 Test 버튼의 `"false"` 가 파이썬에서 **참**이 되어
    미리보기가 실제 적재로 둔갑한다."""
    assert event_args({"apply": "false"}, {"apply": bool}) == {"apply": False}
    assert event_args({"apply": "true"}, {"apply": bool}) == {"apply": True}
    assert event_args({"apply": "0"}, {"apply": bool}) == {"apply": False}


def test_모르는_키는_버린다():
    """스케줄러가 붙이는 메타데이터가 섞여 들어와도 안 깨져야 한다."""
    got = event_args({"limit": 3, "version": "0", "time": "..."}, {"limit": int})
    assert got == {"limit": 3}


def test_없는_키와_None_은_기본값에_맡긴다():
    assert event_args({"limit": None}, {"limit": int, "apply": bool}) == {}
    assert event_args({}, {"limit": int}) == {}


def test_dict_이_아니면_빈값():
    """SQS·ALB 이벤트가 잘못 꽂혀도 터지지 않고 기본값으로 돈다."""
    assert event_args(None, {"limit": int}) == {}
    assert event_args("문자열", {"limit": int}) == {}


# ── time_guard ──────────────────────────────────────────────────────────────
def test_시간이_넉넉하면_계속한다():
    assert time_guard(FakeContext(300_000))() is True


def test_여유분_아래로_내려가면_멈추라고_답한다():
    assert time_guard(FakeContext(10_000))() is False        # 기본 여유 30초


def test_여유분은_조절된다():
    assert time_guard(FakeContext(10_000), reserve_ms=5_000)() is True


def test_context_가_없으면_시간을_안_본다():
    """로컬·CLI 실행 경로 — 프로세스에는 15분 상한이 없으므로 None 이 맞다."""
    assert time_guard(None) is None
    assert time_guard(object()) is None


# ── logger ──────────────────────────────────────────────────────────────────
def test_로거는_레벨이_선다():
    assert logger("t").level > 0
