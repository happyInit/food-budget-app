"""테스트용 fake 어댑터 — 주입 seam에 꽂아 실 DB 없이 핸들러/쿼리를 돌린다. (account/tests/fakes.py 복제)"""
from __future__ import annotations

from collections import deque


class _FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self._c = conn

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, sql, params=None):
        if self._c.raise_exc is not None:
            raise self._c.raise_exc
        self._c.executed.append((" ".join(sql.split()), params))

    async def fetchone(self):
        return self._c.responses.popleft() if self._c.responses else None

    async def fetchall(self):
        out = list(self._c.responses)
        self._c.responses.clear()
        return out


class FakeConn:
    """psycopg async conn의 최소 fake. `responses`를 fetchone/fetchall 순서대로 반환,
    `raise_exc`가 있으면 execute에서 던진다. `executed`에 (정규화 SQL, params) 기록."""

    def __init__(self, responses=(), raise_exc=None) -> None:
        self.responses = deque(responses)
        self.executed: list = []
        self.raise_exc = raise_exc

    def cursor(self):
        return _FakeCursor(self)


class FakePool:
    """lifespan이 실 DB에 붙지 않도록 하는 no-op 풀."""

    async def open(self):
        ...

    async def close(self):
        ...
