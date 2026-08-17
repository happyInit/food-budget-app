"""임프레션 기록 실패가 **조용하지 않은지** — 2026-08-16 사고의 교훈.

`insert_impressions` 는 fail-open 이다(라벨 유실이 추천 응답을 막으면 안 된다). 그건 옳다.
🔴 문제는 종전에 **로그도 카운터도 없었다**는 것이다. 그 대가:

    추천 3건이 화면에 정상 표시됐는데 `activity.recipe_impression` 은 0건이었다.
    설정(IMPRESSION_LOG_ENABLED)·권한(svc_mealplan INSERT)·스키마(11컬럼 일치)·
    프론트(session_id 전송)를 전부 확인했는데도 **원인을 못 찾았다** — 관측 수단이 없어서.

`events.py` 는 같은 교훈으로 이미 카운터를 달아 뒀다(*"session_id 미전송이 3주간 드러나지 않음"*).
노출 쪽에만 안 붙어 있었다. 이 테스트가 그 비대칭을 막는다.

🔴 **로그를 «넣었다» 가 아니라 «나온다» 를 본다** — `observability._OPTIONAL_FIELDS` 허용목록에
   없는 키는 포매터가 조용히 버린다. chat 에서 한 번 그렇게 당했다.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging

import pytest

from app import queries
from app.observability import JsonFormatter


class _BoomCursor:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def executemany(self, *a, **kw):
        raise RuntimeError("boom")


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _BoomConn:
    """executemany 에서 터지는 커넥션 — 권한 오류·타입 오류를 대신한다."""

    def transaction(self):
        return _Tx()

    def cursor(self):
        return _BoomCursor()


class _Ranked:
    def __init__(self, rid: int) -> None:
        self.id = rid
        self.name = f"r{rid}"
        self.score = 1.0
        self.coverage = 0.5
        self.expiring_used = 0
        self.est_cost = 1000
        self.matched_item_ids = ()
        self.image_url = None


@pytest.fixture
def captured():
    """실제 JsonFormatter 를 통과한 출력만 본다(허용목록 포함 검증)."""
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(JsonFormatter(service="mealplan", environment="test"))
    log = logging.getLogger("mealplan")
    log.addHandler(h)
    prev = log.level
    log.setLevel(logging.INFO)
    yield buf
    log.removeHandler(h)
    log.setLevel(prev)


def test_실패해도_추천을_막지_않는다(captured):
    """fail-open 은 유지한다 — 예외가 호출측으로 새어 나가면 추천이 500 이 된다."""
    n = asyncio.run(queries.insert_impressions(
        _BoomConn(), user_id=1, session_id=None, ranked=[_Ranked(1)], budget=None, prefer=None))
    assert n == 0


def test_실패가_조용하지_않다(captured):
    """🔴 이 테스트가 없으면 다음 사람이 로그를 지워도 아무도 모른다."""
    asyncio.run(queries.insert_impressions(
        _BoomConn(), user_id=1, session_id=None,
        ranked=[_Ranked(1), _Ranked(2)], budget=None, prefer=None))

    lines = [ln for ln in captured.getvalue().splitlines() if ln.strip()]
    assert lines, "실패했는데 로그가 한 줄도 없다 — 조용한 실패로 되돌아갔다"
    rec = json.loads(lines[-1])
    assert rec["event"] == "impression_write_failed"
    assert rec["error_type"] == "RuntimeError", "예외 «종류» 가 실려야 원인을 가른다"
    assert rec["record_count"] == 2, "몇 건이 사라졌는지가 실려야 한다"
    assert rec["result"] == "failure"


def test_예외_원문은_싣지_않는다(captured):
    """🔴 SQL 원문·파라미터에는 user_id·session_id 가 섞인다 — 종류만 남긴다(chat 과 같은 규약)."""
    asyncio.run(queries.insert_impressions(
        _BoomConn(), user_id=42, session_id="s", ranked=[_Ranked(1)], budget=None, prefer=None))

    body = captured.getvalue()
    assert "boom" not in body, "예외 메시지 원문이 로그에 실렸다"
    assert "42" not in json.loads(body.splitlines()[-1]).get("message", "")


def test_후보가_없으면_로그도_없다(captured):
    """추천이 0건인 것은 실패가 아니다 — 그때까지 경고를 내면 진짜 실패가 묻힌다."""
    n = asyncio.run(queries.insert_impressions(
        _BoomConn(), user_id=1, session_id=None, ranked=[], budget=None, prefer=None))
    assert n == 0
    assert captured.getvalue().strip() == ""


# ── /health 가 런타임 «유효 플래그» 를 노출하는가 (2026-08-17) ──────────────────
# 🔴 이게 없어서 원인 규명이 막혔다. ConfigMap 은 `true` 인데 `insert_impressions` 가 호출조차
#    되지 않았고(실측: 추천 2xx 3회 · n_tup_ins 320 그대로 · 실패 로그 0건), 코드를 읽어서는
#    더 좁힐 수 없었다. **설정은 «선언» 이 아니라 «파드가 실제로 받은 값» 을 봐야 한다.**
def test_health가_런타임_플래그를_싣는다(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    for k in ("impression_log", "ranking_ml", "event_sink"):
        assert k in body, f"{k} 가 빠졌다 — 이걸 지우면 같은 조사에서 또 막힌다"


def test_health의_플래그는_ctx_settings_를_그대로_읽는다(client, monkeypatch):
    """🔴 별도로 계산하면 «여기선 true 인데 왜» 로 또 갈린다 — 판단에 쓰이는 그 필드여야 한다."""
    from app import main as main_mod

    ctx = main_mod.app.state.ctx
    before = ctx.settings.impression_log_enabled
    monkeypatch.setattr(ctx.settings, "impression_log_enabled", not before)
    assert client.get("/health").json()["impression_log"] is (not before)
