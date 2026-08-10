"""컬리 크롤러의 '조용한 절단' 가드 테스트.

2026-08-03 이 크롤러는 3,324건이 아니라 96건만 긁고 `result: "success"` 로 마감했다.
네트워크 원인(파드 DNS 서치도메인 변조)은 config#139 에서 고쳤지만, **그걸 성공으로
보고한 건 이 코드**였다. 여기서 검증하는 건 "다시 그런 상황이 와도 조용히는 안 지나간다"다.

브라우저·네트워크를 쓰지 않는다 — playwright 는 스텁으로 갈아끼운다.
실행: python -m pytest crawler/kurly/tests -q
"""
import asyncio
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
KURLY_DIR = ROOT / "crawler" / "kurly"


class FakeTimeoutError(Exception):
    """playwright.async_api.TimeoutError 대역."""


def _install_playwright_stubs() -> None:
    """playwright / playwright_stealth 를 스텁으로 등록한다.

    실제 패키지는 chromium 바이너리까지 딸려 오므로 단위 테스트에서 쓰지 않는다.
    prototype 은 임포트 시점에 이 둘을 필요로 하므로 임포트 **전에** 넣어야 한다.
    """
    if "playwright.async_api" in sys.modules:
        return
    pw = types.ModuleType("playwright")
    pw_async = types.ModuleType("playwright.async_api")
    pw_async.TimeoutError = FakeTimeoutError
    pw_async.async_playwright = lambda: None
    pw.async_api = pw_async
    sys.modules["playwright"] = pw
    sys.modules["playwright.async_api"] = pw_async

    stealth_mod = types.ModuleType("playwright_stealth")

    class Stealth:  # run() 테스트에서 monkeypatch 로 갈아끼운다
        def use_async(self, _):
            raise NotImplementedError

    stealth_mod.Stealth = Stealth
    sys.modules["playwright_stealth"] = stealth_mod


_install_playwright_stubs()
sys.path.insert(0, str(KURLY_DIR))
import prototype  # noqa: E402


class FakePage:
    """goto 호출을 기록하고, 지정한 시도에서만 성공하는 가짜 페이지."""

    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.goto_calls: list[str] = []

    async def goto(self, url, **_kw):
        self.goto_calls.append(url)
        if len(self.goto_calls) <= self.fail_times:
            raise FakeTimeoutError("Timeout 50000ms exceeded")

    async def wait_for_timeout(self, _ms):
        return None


def _product(pid: str) -> dict:
    return {"product_id": pid, "name": f"상품{pid}", "sale_price": 1000}


def _pages(monkeypatch, pages: list[list[dict]]) -> None:
    """parse_page 가 호출될 때마다 pages 를 순서대로 반환하게 한다."""
    seq = iter(pages)

    async def fake_parse_page(_page):
        return next(seq, [])

    monkeypatch.setattr(prototype.kurly, "parse_page", fake_parse_page)


# ── ① 1페이지 0건 = 실패 ────────────────────────────────────────────────────────

def test_1페이지가_비면_페이지네이션_끝이_아니라_실패다(monkeypatch):
    """종전에는 이 경우 곧장 break 하고 'success' 로 마감했다 — 사고의 본체."""
    _pages(monkeypatch, [[]])
    with pytest.raises(prototype.CrawlTruncatedError):
        asyncio.run(prototype.crawl_category(FakePage(), "907", "채소"))


def test_2페이지부터_비는_것은_정상_종료다(monkeypatch):
    """부분 페이지로 끝나는 건 실제 페이지네이션의 정상 모습이라 실패로 보면 안 된다."""
    _pages(monkeypatch, [[_product("1"), _product("2")], []])
    got = asyncio.run(prototype.crawl_category(FakePage(), "907", "채소"))
    assert [p["product_id"] for p in got] == ["1", "2"]


def test_중복_상품만_돌아와도_종료한다(monkeypatch):
    """페이지 파라미터가 무시돼 같은 페이지가 반복되면 new_products 가 0이 되어 끝난다."""
    same = [_product("1")]
    _pages(monkeypatch, [same, same])
    got = asyncio.run(prototype.crawl_category(FakePage(), "907", "채소"))
    assert len(got) == 1


# ── ② goto 재시도 ──────────────────────────────────────────────────────────────

def test_goto_는_타임아웃을_재시도한다(monkeypatch):
    """차단은 RST 가 아니라 무응답으로 오므로 증상이 늘 타임아웃이다."""
    page = FakePage(fail_times=prototype.GOTO_ATTEMPTS - 1)
    asyncio.run(prototype._goto_with_retry(page, "https://www.kurly.com/x", "907"))
    assert len(page.goto_calls) == prototype.GOTO_ATTEMPTS


def test_goto_는_재시도를_소진하면_예외를_올린다():
    page = FakePage(fail_times=prototype.GOTO_ATTEMPTS)
    with pytest.raises(FakeTimeoutError):
        asyncio.run(prototype._goto_with_retry(page, "https://www.kurly.com/x", "907"))
    assert len(page.goto_calls) == prototype.GOTO_ATTEMPTS


# ── ③ 잡 전체 — 카테고리 격리 · 총합 하한 · 종료코드 ────────────────────────────

class _FakeBrowser:
    def __init__(self, page):
        self._page = page

    async def new_context(self, **_kw):
        return self

    async def new_page(self):
        return self._page

    async def close(self):
        return None


class _FakeChromium:
    def __init__(self, page):
        self._page = page

    async def launch(self, **_kw):
        return _FakeBrowser(self._page)


class _FakeCM:
    def __init__(self, page):
        self._page = page

    async def __aenter__(self):
        return types.SimpleNamespace(chromium=_FakeChromium(self._page))

    async def __aexit__(self, *_a):
        return False


def _fake_browser_stack(monkeypatch, page):
    monkeypatch.setattr(prototype, "async_playwright", lambda: None)
    monkeypatch.setattr(
        prototype, "Stealth",
        lambda: types.SimpleNamespace(use_async=lambda _: _FakeCM(page)),
    )


def test_수확이_하한보다_적으면_종료코드_1(monkeypatch, tmp_path):
    """2026-08-03 재현 — 96건을 긁고 'success' 로 끝나던 자리."""
    monkeypatch.setattr(prototype, "CATEGORIES", {"907": "채소"})
    _fake_browser_stack(monkeypatch, FakePage())
    _pages(monkeypatch, [[_product(str(i)) for i in range(96)], []])

    rc = asyncio.run(prototype.run(kafka=False, out=str(tmp_path / "out.json")))
    assert rc == 1, "정상의 1/34 만 긁고도 성공으로 마감하면 안 된다"


def test_한_카테고리가_죽어도_나머지는_걷고_종료코드_1(monkeypatch, tmp_path):
    """종전엔 첫 카테고리 실패가 나머지 3개를 통째로 날렸다(그날 수확 0건)."""
    monkeypatch.setattr(prototype, "CATEGORIES", {"907": "채소", "908": "과일"})
    monkeypatch.setattr(prototype, "MIN_TOTAL_RECORDS", 1)
    _fake_browser_stack(monkeypatch, FakePage())
    # 907 = 1페이지 0건(실패) → 908 = 정상 2건
    _pages(monkeypatch, [[], [_product("1"), _product("2")], []])

    out = tmp_path / "out.json"
    rc = asyncio.run(prototype.run(kafka=False, out=str(out)))
    assert rc == 1, "부분 실패는 성공으로 보고하면 안 된다"
    assert '"product_id": "1"' in out.read_text(encoding="utf-8"), "살아남은 카테고리는 걷혀야 한다"


def test_정상_수확은_종료코드_0(monkeypatch, tmp_path):
    monkeypatch.setattr(prototype, "CATEGORIES", {"907": "채소"})
    monkeypatch.setattr(prototype, "MIN_TOTAL_RECORDS", 2)
    _fake_browser_stack(monkeypatch, FakePage())
    _pages(monkeypatch, [[_product("1"), _product("2")], []])

    rc = asyncio.run(prototype.run(kafka=False, out=str(tmp_path / "out.json")))
    assert rc == 0


# ── ④ Kafka 전달 실패 = 실패 (#558) ────────────────────────────────────────────
#    ①~③ 은 "긁다 만 것"을 잡는다. 이건 **"보내다 만 것"** 이다.
#    종전엔 `closers` 에 `prod.flush` 를 넣고 반환값을 버려서, 크롤이 완벽해도 전달이
#    통째로 실패하면 그대로 `result: "success"` 였다.
#    🔴 이관 후엔 크롤러=온프렘 / 브로커=AWS 라 터널 5분 단절이 곧 그 회차 통째 유실이다.

sys.path.insert(0, str(ROOT / "pipelines" / "stream"))
import _delivery  # noqa: E402


class _KafkaErr(Exception):
    """confluent_kafka.KafkaError 대역."""

    def name(self):
        return "_MSG_TIMED_OUT"

    def fatal(self):
        return False


class _StubMsg:
    def topic(self):
        return "retail.crawl.raw"


class _StubProducer:
    """librdkafka 의 관측된 동작: **실패한 메시지도 큐에서는 빠진다**(→ flush 는 0)."""

    def __init__(self, err=None, stuck=0):
        self.err, self.stuck, self.queue = err, stuck, []

    def produce(self, *_a, **_kw):
        self.queue.append(1)

    def poll(self, _t=0):
        return 0

    def flush(self, _t=None):
        sent, self.queue = self.queue[self.stuck:], self.queue[:self.stuck]
        for _ in sent:
            _delivery.tracker().on_delivery(self.err, _StubMsg())
        return len(self.queue)


@pytest.fixture(autouse=True)
def _fresh_tracker():
    _delivery.reset_tracker()
    yield
    _delivery.reset_tracker()


def _kafka_stub(monkeypatch, prod):
    monkeypatch.setattr(prototype, "_kafka_sink",
                        lambda: (lambda rec: prod.produce(rec), prod, "kafka:test"))


def test_전달이_전부_실패하면_크롤이_완벽해도_종료코드_1(monkeypatch):
    """🔴 flush 는 0 을 돌려준다 — 그걸 믿으면 유실을 성공으로 마감한다."""
    monkeypatch.setattr(prototype, "CATEGORIES", {"907": "채소"})
    monkeypatch.setattr(prototype, "MIN_TOTAL_RECORDS", 2)
    _fake_browser_stack(monkeypatch, FakePage())
    _pages(monkeypatch, [[_product("1"), _product("2")], []])
    prod = _StubProducer(err=_KafkaErr())
    _kafka_stub(monkeypatch, prod)

    rc = asyncio.run(prototype.run(kafka=True))
    assert prod.flush(0) == 0, "큐는 비어 있다 — 그래서 flush 만 보면 성공으로 보인다"
    assert rc == 1, "전달 실패는 성공으로 마감하면 안 된다"


def test_전달이_큐에_남아도_종료코드_1(monkeypatch):
    monkeypatch.setattr(prototype, "CATEGORIES", {"907": "채소"})
    monkeypatch.setattr(prototype, "MIN_TOTAL_RECORDS", 2)
    _fake_browser_stack(monkeypatch, FakePage())
    _pages(monkeypatch, [[_product("1"), _product("2")], []])
    _kafka_stub(monkeypatch, _StubProducer(stuck=1))

    assert asyncio.run(prototype.run(kafka=True)) == 1


def test_전달이_전건_확인되면_종료코드_0(monkeypatch):
    monkeypatch.setattr(prototype, "CATEGORIES", {"907": "채소"})
    monkeypatch.setattr(prototype, "MIN_TOTAL_RECORDS", 2)
    _fake_browser_stack(monkeypatch, FakePage())
    _pages(monkeypatch, [[_product("1"), _product("2")], []])
    _kafka_stub(monkeypatch, _StubProducer())

    assert asyncio.run(prototype.run(kafka=True)) == 0
