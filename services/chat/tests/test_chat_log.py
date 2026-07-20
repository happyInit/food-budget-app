"""chat_message 영속 게이팅 — flag off / 미인증(user_id None)이면 DB를 건드리지 않음(무동작)."""
from types import SimpleNamespace

import pytest

from app.pipeline import chat_log


class _BoomPool:
    """건드리면 실패 — 무동작 경로에서 pool이 안 열리는지 검증용."""
    def connection(self):
        raise AssertionError("무동작이어야 하는데 pool을 열었다")


def _q():
    return SimpleNamespace(intent="recommend", item_ids=[1, 2])


def _r():
    return SimpleNamespace(reply="응답", unanswered=False, basis=[])


@pytest.mark.asyncio
async def test_noop_when_flag_off(monkeypatch):
    monkeypatch.setattr(chat_log.settings, "chat_persist_enabled", False, raising=False)
    await chat_log.persist_turns(_BoomPool(), 1, "sess", "안녕", _q(), _r())   # 무동작(예외 없음)


@pytest.mark.asyncio
async def test_noop_when_unauthenticated(monkeypatch):
    monkeypatch.setattr(chat_log.settings, "chat_persist_enabled", True, raising=False)
    await chat_log.persist_turns(_BoomPool(), None, "sess", "안녕", _q(), _r())  # user_id None → skip


@pytest.mark.asyncio
async def test_noop_when_no_session(monkeypatch):
    monkeypatch.setattr(chat_log.settings, "chat_persist_enabled", True, raising=False)
    await chat_log.persist_turns(_BoomPool(), 1, None, "안녕", _q(), _r())        # session 없음 → skip
