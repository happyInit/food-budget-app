"""발행 경로 CLI 검증 — `main()` 을 **실제로 돌린다** 〔이슈 #641〕.

🔴 왜 이 파일이 생겼나 — 기존 테스트는 `detect()` 같은 **순수 함수만** 검증했다.
그래서 `--emit-direct` 를 추가했을 때 CLI 배선이 깨진 걸 아무도 못 잡았다:

    `ripe`·`id_by_idx` 가 `if args.emit:` **안에서** 정의되는데
    `--emit-direct` 블록은 형제 블록이라 → `NameError` (단독 실행이 곧 의도된 사용법인데도)

**유닛 테스트가 다 통과해도 진입점이 안 돌 수 있다.** 그 간극을 여기서 막는다.

DB·Kafka 없이 돈다 — `main()` 이 부르는 외부 경계(조회·영속화·발행)만 가짜로 바꾼다.
"""
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import detect_price_anomaly as d  # noqa: E402


@dataclass
class _Anom:
    """`detect()` 가 돌려주는 Anomaly 의 최소 형태 — `asdict()` 가 돌면 된다."""
    item_id: int = 1
    canonical_name: str = "고구마"
    source: str = "kurly"
    observed_at: str = "2026-08-13"
    price_100g: float = 300.0
    baseline_mean: float = 500.0
    baseline_std: float = 40.0
    drop_pct: float = 40.0
    is_record_low: bool = True
    discount_rate: float | None = None
    z_score: float = -5.0
    samples: int = 30                 # 성숙(기본 게이트 통과)
    retail_product_id: int = 1001
    crawled_at: str = "2026-08-13T09:00:00"
    price: float = 1500.0


@pytest.fixture()
def wired(monkeypatch):
    """`main()` 의 외부 경계를 전부 가짜로 — 무엇이 호출됐는지만 관찰한다."""
    seen = {"kafka": 0, "fanout": 0, "published": []}

    monkeypatch.setattr(d, "persist_baselines", lambda *a, **k: 0)
    monkeypatch.setattr(d, "persist_anomalies", lambda *a, **k: [777])
    monkeypatch.setattr(d, "mark_published",
                        lambda conn, ids: seen["published"].extend(ids))

    class _Cur:
        rowcount = 1

        def execute(self, *a, **k): ...
        def fetchall(self): return []
        def fetchone(self): return (0,)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Conn:
        # psycopg3 형태 — `conn.execute(sql, params).fetchall()` 과 `with conn.cursor() as cur` 둘 다 쓴다
        def execute(self, *a, **k): return _Cur()
        def cursor(self): return _Cur()
        def commit(self): ...
        def rollback(self): ...
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(d, "connect", lambda *a, **k: _Conn())

    # 발행 두 경로 — 실제 모듈을 대신한다(임포트 시점이 함수 안이라 sys.modules 로 넣는다)
    import types
    kafka_mod = types.ModuleType("produce_price_anomaly")
    kafka_mod.emit_anomalies = lambda payloads: seen.__setitem__("kafka", len(payloads)) or len(payloads)
    kafka_mod.build_anomaly_event = lambda a: {"item_id": a["item_id"], "anomaly_db_id": a.get("db_id")}
    consumer_mod = types.ModuleType("consume_price_anomaly")

    def _fanout(cur, ev):
        seen["fanout"] += 1
        return 1
    consumer_mod.fanout = _fanout
    monkeypatch.setitem(sys.modules, "produce_price_anomaly", kafka_mod)
    monkeypatch.setitem(sys.modules, "consume_price_anomaly", consumer_mod)

    monkeypatch.setattr(d, "detect", lambda *a, **k: [_Anom()])
    return seen


def _run(argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["detect_price_anomaly.py", *argv])
    d.main()


# ── 🔴 이슈 #641 의 본체 — 단독 실행이 죽지 않는다 ──────────────────────
def test_emit_direct_alone_runs(wired, monkeypatch, capsys):
    _run(["--emit-direct"], monkeypatch)      # 종전: NameError: name 'ripe' is not defined
    assert wired["fanout"] == 1
    assert wired["kafka"] == 0, "직접 경로인데 Kafka 를 불렀다"
    assert wired["published"] == [777], "fan-out 성공 뒤 published_at 을 찍어야 한다"


def test_emit_alone_unchanged(wired, monkeypatch):
    _run(["--emit"], monkeypatch)
    assert wired["kafka"] == 1
    assert wired["fanout"] == 0, "Kafka 경로인데 직접 fan-out 을 했다"


# ── 🔴 2차 함정 — 성숙도 게이트가 두 경로에 같이 걸린다 ─────────────────
def test_maturity_gate_applies_to_emit_direct(wired, monkeypatch, capsys):
    """게이트를 같이 안 옮기면 **미성숙 오탐이 사용자 알림으로 직접 간다.**"""
    monkeypatch.setattr(d, "detect", lambda *a, **k: [_Anom(samples=3)])   # 미성숙
    _run(["--emit-direct"], monkeypatch)
    assert wired["fanout"] == 0, "🔴 미성숙 건이 알림으로 나갔다"
    assert "성숙도 게이트" in capsys.readouterr().out


def test_maturity_gate_can_be_overridden(wired, monkeypatch):
    monkeypatch.setattr(d, "detect", lambda *a, **k: [_Anom(samples=3)])
    _run(["--emit-direct", "--allow-immature"], monkeypatch)
    assert wired["fanout"] == 1


# ── 목적지는 하나 (C-88) ────────────────────────────────────────────────
def test_both_flags_rejected(wired, monkeypatch):
    with pytest.raises(SystemExit) as e:
        _run(["--emit", "--emit-direct"], monkeypatch)
    assert e.value.code == 2, "argparse 사용법 오류로 거절해야 한다"
    assert wired["kafka"] == 0 and wired["fanout"] == 0


# ── 발행 안 할 때는 두 경로 다 안 돈다 (기본 dry-run) ───────────────────
def test_dry_run_publishes_nothing(wired, monkeypatch):
    _run([], monkeypatch)
    assert wired["kafka"] == 0 and wired["fanout"] == 0 and wired["published"] == []
