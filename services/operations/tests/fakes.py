from __future__ import annotations

from collections import deque


class _FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self._conn = conn

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, sql, params=None):
        self._conn.executed.append((" ".join(sql.split()), params))

    async def fetchall(self):
        return self._conn.responses.popleft() if self._conn.responses else []


class FakeConn:
    """Minimal async psycopg connection fake for route and query tests."""

    def __init__(self, responses=()) -> None:
        self.responses = deque(responses)
        self.executed: list[tuple[str, object]] = []

    def cursor(self):
        return _FakeCursor(self)
