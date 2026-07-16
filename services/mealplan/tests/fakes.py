"""테스트용 fake 어댑터 — 주입 seam에 꽂아 실 DB·크로스서비스 없이 핸들러/쿼리를 돌린다.
account/tests/fakes.py 를 복제 + (1) 다중 문(checkout) 지원 (2) budget/pantry fake provider.
"""
from __future__ import annotations

from collections import deque

from app.context import PantryStock, ProviderUnavailable


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
        self._c._advance()          # 문장 1개당 결과셋 1개 소비

    async def fetchone(self):
        return self._c._one()

    async def fetchall(self):
        return self._c._all()


class FakeConn:
    """psycopg async conn의 최소 fake.

    두 모드:
      responses=[row, ...]         단일-문 모드(전부 한 결과셋) — account 호환.
      results=[[row,...], [...]]   문장별 결과셋(checkout 처럼 한 conn 다중 문).
    `execute` 마다 다음 결과셋으로 넘어가고 fetchone=현재셋 popleft / fetchall=현재셋 drain.
    `raise_exc` 가 있으면 execute 에서 던진다(예: 제약 위반). `executed`에 (정규화SQL, params) 기록
    → WHERE user_id 파라미터가 실렸는지 검증.
    """

    def __init__(self, responses=None, results=None, raise_exc=None) -> None:
        if results is not None:
            self._sets = deque(deque(rs) for rs in results)
        elif responses is not None:
            self._sets = deque([deque(responses)])
        else:
            self._sets = deque()
        self._active: deque | None = None
        self.executed: list = []
        self.raise_exc = raise_exc

    def _advance(self):
        self._active = self._sets.popleft() if self._sets else deque()

    def _one(self):
        if self._active is None:
            self._advance()
        return self._active.popleft() if self._active else None

    def _all(self):
        if self._active is None:
            self._advance()
        out = list(self._active)
        self._active.clear()
        return out

    def cursor(self):
        return _FakeCursor(self)


class FakePool:
    """lifespan이 실 DB에 붙지 않도록 하는 no-op 풀."""

    async def open(self):
        ...

    async def close(self):
        ...


# ── 크로스서비스 seam fake ──────────────────────────────────────────────────
class FakeBudgetProvider:
    def __init__(self, amount=None, unavailable=False):
        self._amount = amount
        self._unavailable = unavailable

    async def get_budget(self, user_id: int):
        if self._unavailable:
            raise ProviderUnavailable("fake budget down")
        return self._amount


class FakePantryProvider:
    def __init__(self, stock=None, saved=None, unavailable=False):
        self._stock = list(stock or [])
        self._saved = saved
        self._unavailable = unavailable

    async def get_pantry(self, user_id: int):
        if self._unavailable:
            raise ProviderUnavailable("fake pantry down")
        return self._stock

    async def saved_ingredients(self, user_id: int):
        if self._unavailable:
            raise ProviderUnavailable("fake pantry down")
        return self._saved


class FakeExclusionProvider:
    def __init__(self, excluded=None, unavailable=False):
        self._excluded = list(excluded or [])
        self._unavailable = unavailable

    async def get_excluded_item_ids(self, user_id: int):
        if self._unavailable:
            raise ProviderUnavailable("fake exclusion down")
        return self._excluded


def stock(item_id: int, name: str = "재료", expiring: bool = False) -> PantryStock:
    return PantryStock(item_id=item_id, name=name, expiring=expiring)
