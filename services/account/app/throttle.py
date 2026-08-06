"""로그인 스로틀 — bcrypt CPU 몰림/무차별대입 방어 (#534, k6 부하테스트 후속).

성격이 다른 두 방어를 한 곳에 묶는다(전부 in-memory·pod 로컬 → Redis 불요):

  [1] 동시성 캡(bulkhead) — bcrypt(cost 12 ≈ 200ms CPU) 동시 실행 수를 코어급으로 제한한다.
      한계를 넘으면 큐에 쌓지 않고 즉시 429 → 알림 fan-out 로그인 몰림 때 '전원 대기' 대신
      감당분만 빠르게 처리하고 초과분은 ~1ms 에 흘려보낸다(회원가입·타 엔드포인트도 같이 안 죽음).
  [2] 고정창 카운터 — 이메일/IP 당 창(window)내 로그인 시도 상한. 무차별대입·크리덴셜 스터핑 방어.

⚠️ bcrypt cost 는 낮추지 않는다(#534 — 무차별대입 저항이 본래 기능이다).
⚠️ 처리량 천장(≈50 logins/s = bcrypt×코어)은 코드로 못 올린다. 이 모듈은 처리량이 아니라
   **실패 방식**을 바꾼다 — 전원 지연 → (감당분 정상 + 초과분 빠른 429).
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from fastapi import HTTPException, Request


def client_ip(request: Request) -> str | None:
    """실 클라이언트 IP. account 는 uvicorn --proxy-headers 없이 뜨므로 request.client 는
    Istio 사이드카(전원 동일)가 된다 → X-Forwarded-For 첫 홉을 신뢰한다(GW 1홉 전제).
    XFF 가 없으면(직결·테스트) peer 로 폴백."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    return request.client.host if request.client else None


class _BcryptGate:
    """동시 bcrypt 실행 수를 제한하는 bulkhead. 한계 초과분은 대기시키지 않고 즉시 거절한다.

    _inflight = 승인된(실행 + 세마포어 대기) 요청 수. 이벤트 루프는 단일 스레드라 검사~증가 사이에
    await 가 없어 원자적이다(락 불요). max_waiting 만큼 얕은 큐를 허용하고 그 위는 429."""

    def __init__(self, max_concurrent: int, max_waiting: int) -> None:
        self._concurrent = max(1, max_concurrent)
        self._sem = asyncio.Semaphore(self._concurrent)
        self._limit = self._concurrent + max(0, max_waiting)
        self._inflight = 0

    @property
    def inflight(self) -> int:
        return self._inflight

    async def run(self, fn: Callable, *args):
        if self._inflight >= self._limit:
            raise HTTPException(
                429, "일시적으로 로그인 요청이 많습니다. 잠시 후 다시 시도해 주세요.",
                headers={"Retry-After": "1"})
        self._inflight += 1
        try:
            async with self._sem:
                return await asyncio.to_thread(fn, *args)
        finally:
            self._inflight -= 1


class _FixedWindow:
    """키별 고정창 카운터(in-memory). 창이 지나면 통째 리셋 → 메모리는 한 창의 활성 키 수로 상한.
    limit<=0 이면 비활성(항상 통과 — per-IP 를 끄고 싶을 때)."""

    def __init__(self, limit: int, window_s: int) -> None:
        self._limit = limit
        self._window = max(1, window_s)
        self._counts: dict[str, int] = {}
        self._start = 0.0

    def allow(self, key: str, now: float) -> bool:
        if self._limit <= 0:
            return True
        if now - self._start >= self._window:
            self._counts = {}          # 창 전환 → 옛 카운터 폐기(메모리 상한)
            self._start = now
        n = self._counts.get(key, 0) + 1
        self._counts[key] = n
        return n <= self._limit


class LoginThrottle:
    """로그인/회원가입 경로가 Depends 로 받는 스로틀. 시계 주입 가능 → DB·네트워크 없이 테스트된다."""

    def __init__(self, *, bcrypt_max_concurrent: int, bcrypt_max_waiting: int,
                 per_email: int, per_ip: int, window_s: int) -> None:
        self._gate = _BcryptGate(bcrypt_max_concurrent, bcrypt_max_waiting)
        self._email = _FixedWindow(per_email, window_s)
        self._ip = _FixedWindow(per_ip, window_s)
        self._window_s = max(1, window_s)

    def check_login(self, email: str, ip: str | None, now: float | None = None) -> None:
        """이메일/IP 창 한도 검사 — bcrypt **이전**에 호출해 공격의 서버 비용을 0 으로 만든다.
        초과 시 429(Retry-After)."""
        now = time.monotonic() if now is None else now
        if not self._email.allow(f"e:{email.strip().lower()}", now):
            raise self._too_many()
        if ip and not self._ip.allow(f"i:{ip}", now):
            raise self._too_many()

    async def run_bcrypt(self, fn: Callable, *args):
        """bcrypt 호출을 동시성 캡 안에서 스레드로 오프로드한다. 한계 초과면 429."""
        return await self._gate.run(fn, *args)

    def _too_many(self) -> HTTPException:
        return HTTPException(
            429, "로그인 시도가 너무 잦습니다. 잠시 후 다시 시도해 주세요.",
            headers={"Retry-After": str(self._window_s)})

    @property
    def bcrypt_inflight(self) -> int:
        return self._gate.inflight
