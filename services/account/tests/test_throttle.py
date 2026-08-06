"""로그인 스로틀 테스트 — DB·네트워크 없이(#534).

[1] 고정창: 시계를 주입해 창 리셋까지 결정적으로 검증.
[2] 동시성 캡: 세마포어를 붙잡은 채 in-flight 를 채워 초과분 429 를 검증.
[3] 라우트 통합: get_throttle 를 빡빡한 스로틀로 override → /login 반복 시 429.
"""
from __future__ import annotations

import asyncio

import pytest

import app.main as main_mod
from app.context import get_conn, get_security, get_throttle
from app.security import Security
from app.throttle import LoginThrottle, _BcryptGate, _FixedWindow
from tests.fakes import FakeConn

OV = main_mod.app.dependency_overrides
SEC = Security("test-secret")


# ── [1] 고정창 ──────────────────────────────────────────────────────────
def test_fixed_window_blocks_over_limit():
    w = _FixedWindow(limit=3, window_s=60)
    assert [w.allow("k", now=100.0) for _ in range(4)] == [True, True, True, False]


def test_fixed_window_resets_after_window():
    w = _FixedWindow(limit=1, window_s=60)
    assert w.allow("k", now=100.0) is True
    assert w.allow("k", now=120.0) is False      # 같은 창 → 차단
    assert w.allow("k", now=161.0) is True        # 창(60s) 경과 → 리셋


def test_fixed_window_keys_are_independent():
    w = _FixedWindow(limit=1, window_s=60)
    assert w.allow("a", now=100.0) is True
    assert w.allow("b", now=100.0) is True        # 다른 키는 별도 카운터
    assert w.allow("a", now=100.0) is False


def test_fixed_window_disabled_when_limit_zero():
    w = _FixedWindow(limit=0, window_s=60)
    assert all(w.allow("k", now=100.0) for _ in range(1000))  # 0 = 끔 → 항상 통과


def test_check_login_raises_429_over_email_limit():
    t = LoginThrottle(bcrypt_max_concurrent=8, bcrypt_max_waiting=8,
                      per_email=2, per_ip=0, window_s=60)
    t.check_login("a@b.com", ip=None, now=100.0)
    t.check_login("a@b.com", ip=None, now=100.0)
    with pytest.raises(Exception) as ei:
        t.check_login("a@b.com", ip=None, now=100.0)
    assert ei.value.status_code == 429


def test_check_login_email_is_case_insensitive():
    t = LoginThrottle(bcrypt_max_concurrent=8, bcrypt_max_waiting=8,
                      per_email=1, per_ip=0, window_s=60)
    t.check_login("A@B.com", ip=None, now=100.0)
    with pytest.raises(Exception) as ei:
        t.check_login("a@b.com", ip=None, now=100.0)  # 대소문자 무시 → 같은 키
    assert ei.value.status_code == 429


def test_check_login_per_ip_limit():
    t = LoginThrottle(bcrypt_max_concurrent=8, bcrypt_max_waiting=8,
                      per_email=0, per_ip=2, window_s=60)
    # 이메일은 매번 달라도 같은 IP 면 창 한도에 걸린다(크리덴셜 스터핑 방어).
    t.check_login("a@x.com", ip="9.9.9.9", now=100.0)
    t.check_login("b@x.com", ip="9.9.9.9", now=100.0)
    with pytest.raises(Exception) as ei:
        t.check_login("c@x.com", ip="9.9.9.9", now=100.0)
    assert ei.value.status_code == 429


# ── [2] 동시성 캡 ───────────────────────────────────────────────────────
def test_bcrypt_gate_sheds_when_full():
    async def scenario():
        gate = _BcryptGate(max_concurrent=1, max_waiting=1)  # 동시 1 + 대기 1 = 한도 2
        release = asyncio.Event()

        def blocker():
            # to_thread 안에서 도는 동기 함수 → 루프를 막지 않고 release 를 폴링한다.
            import time as _t
            while not release.is_set():
                _t.sleep(0.005)
            return "done"

        # 1) 실행 슬롯 점유, 2) 대기 슬롯 점유 → in-flight 2/2
        t1 = asyncio.create_task(gate.run(blocker))
        t2 = asyncio.create_task(gate.run(blocker))
        # 두 태스크가 gate.run 에 진입해 _inflight 를 채울 때까지 양보
        for _ in range(50):
            await asyncio.sleep(0)
            if gate.inflight >= 2:
                break
        assert gate.inflight == 2
        # 3) 한도 초과 → 즉시 429
        with pytest.raises(Exception) as ei:
            await gate.run(blocker)
        assert ei.value.status_code == 429
        # 마무리: 블로커 해제 후 정리
        release.set()
        await asyncio.gather(t1, t2)
        assert gate.inflight == 0

    asyncio.run(scenario())


def test_bcrypt_gate_runs_and_returns_value():
    async def scenario():
        gate = _BcryptGate(max_concurrent=2, max_waiting=2)
        out = await gate.run(lambda a, b: a + b, 2, 3)
        assert out == 5
        assert gate.inflight == 0
    asyncio.run(scenario())


# ── [3] 라우트 통합 (get_throttle override) ──────────────────────────────
def test_login_rate_limited_returns_429(client):
    h = SEC.hash_password("hunter2!!")
    OV[get_conn] = lambda: FakeConn(responses=[{"id": 7, "password_hash": h, "provider": "local"}])
    OV[get_security] = lambda: SEC
    throttle = LoginThrottle(  # 단일 인스턴스 — 요청 간 카운터 공유(람다로 매번 새로 만들면 리셋됨)
        bcrypt_max_concurrent=8, bcrypt_max_waiting=8, per_email=2, per_ip=0, window_s=60)
    OV[get_throttle] = lambda: throttle
    body = {"email": "a@b.com", "password": "hunter2!!"}
    assert client.post("/api/auth/login", json=body).status_code == 200
    # FakeConn responses 는 1회 소진 → 이후는 row None(401)이지만, 3번째는 창 한도라 bcrypt 전에 429.
    OV[get_conn] = lambda: FakeConn(responses=[{"id": 7, "password_hash": h, "provider": "local"}])
    assert client.post("/api/auth/login", json=body).status_code == 200
    r = client.post("/api/auth/login", json=body)
    assert r.status_code == 429
    assert "Retry-After" in r.headers
