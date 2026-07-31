"""최저가 fan-out 컨슈머 — 알림 문구·쿨다운·수신자 필터 계약 검증(Kafka·PG 불필요).

이 컨슈머는 **유저에게 직접 나가는 알림**을 만든다. 되돌릴 수 없으므로
"누구에게 보내는가"와 "무엇이 보이는가"를 코드 밖에서 고정해 둔다.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "stream"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from produce_price_anomaly import build_anomaly_event  # noqa: E402


def _anomaly(**over):
    base = {
        "item_id": 42, "canonical_name": "삼겹살", "source": "oasis",
        "observed_at": "2026-07-29", "price_100g": 1180.0, "baseline_mean": 1600.0,
        "drop_pct": 26.25, "z_score": -2.6, "samples": 12,
        "is_record_low": False, "discount_rate": 30,
    }
    base.update(over)
    return base


# ── 발행 계약 ────────────────────────────────────────────────────────────────
def test_anomaly_id_is_stable_for_same_observation():
    """같은 품목·소스·관측일이면 멱등키가 같아야 재실행 시 중복 알림을 막을 수 있다."""
    a = build_anomaly_event(_anomaly())
    b = build_anomaly_event(_anomaly(price_100g=1170.0))     # 값이 조금 달라도 같은 관측
    assert a["anomaly_id"] == b["anomaly_id"] == "42:oasis:2026-07-29"


def test_anomaly_id_differs_across_sources():
    """소스가 다르면 별개 관측 — 이마트 급락과 오아시스 급락은 각각 알릴 수 있어야 한다."""
    a = build_anomaly_event(_anomaly(source="oasis"))
    b = build_anomaly_event(_anomaly(source="emart"))
    assert a["anomaly_id"] != b["anomaly_id"]


def test_event_carries_fields_needed_for_notification():
    ev = build_anomaly_event(_anomaly())
    for k in ("item_id", "canonical_name", "price_100g", "baseline_mean", "drop_pct", "is_record_low"):
        assert ev[k] is not None, k
    assert json.dumps(ev, ensure_ascii=False)                # 직렬화 가능해야 발행된다


# ── 알림 문구 ────────────────────────────────────────────────────────────────
def _load_consumer():
    """컨슈머 모듈은 Kafka·PG 드라이버 **없이** 임포트돼야 한다(정책 함수 검증 가능성)."""
    import consume_price_anomaly as m
    return m


def test_notification_text_shows_price_and_drop():
    m = _load_consumer()
    title, body = m.build_notification(build_anomaly_event(_anomaly()))
    assert "삼겹살" in title and "26%" in title
    assert "1,180원" in body and "1,600원" in body     # 지금 값과 비교 기준을 모두 보여준다


def test_record_low_gets_its_own_title():
    """역대 최저가는 '몇 % 하락'보다 강한 신호라 제목이 달라야 한다."""
    m = _load_consumer()
    title, _ = m.build_notification(build_anomaly_event(_anomaly(is_record_low=True)))
    assert "역대 최저가" in title


def test_notification_survives_missing_optional_fields():
    """canonical_name·할인율이 비어도 알림이 깨지지 않아야 한다(미매칭 품목)."""
    m = _load_consumer()
    ev = build_anomaly_event(_anomaly(canonical_name=None, discount_rate=None))
    title, body = m.build_notification(ev)
    assert title and body


# ── 수신자 필터(SQL 계약) ────────────────────────────────────────────────────
class _FakeCur:
    def __init__(self):
        self.sql = self.params = None
        self.rowcount = 3

    def execute(self, sql, params):
        self.sql, self.params = sql, params


def test_fanout_targets_only_watchers_with_cooldown_and_setting():
    """세 조건이 모두 SQL에 있어야 한다 — 관심 등록 · 알림 설정 ON · 쿨다운 경과."""
    m = _load_consumer()
    cur = _FakeCur()
    made = m.fanout(cur, build_anomaly_event(_anomaly()))

    assert made == 3
    assert "price.price_watch" in cur.sql                 # 관심 등록자만
    assert "notification_setting" in cur.sql              # 알림 끈 유저 제외
    assert "COALESCE(s.low_price, true)" in cur.sql       # 설정 행 없으면 기본 수신
    assert "NOT EXISTS" in cur.sql                        # 쿨다운
    assert cur.params["cooldown"] == m.COOLDOWN_DAYS == 7
    assert cur.params["item_id"] == 42


def test_fanout_payload_has_item_id_for_deeplink_and_cooldown():
    """payload.item_id 는 딥링크에도, 쿨다운 조회(payload->>'item_id')에도 쓰인다."""
    m = _load_consumer()
    cur = _FakeCur()
    m.fanout(cur, build_anomaly_event(_anomaly()))
    payload = json.loads(cur.params["payload"])
    assert payload["item_id"] == 42
    assert payload["anomaly_id"] == "42:oasis:2026-07-29"
    assert cur.params["item_id_text"] == "42"             # jsonb 비교는 문자열이라 타입이 맞아야 한다


def test_fanout_returns_zero_when_nobody_watches():
    """관심 등록자가 없으면 0건 — 알림 없이 정상 처리(에러 아님)."""
    m = _load_consumer()
    cur = _FakeCur()
    cur.rowcount = 0
    assert m.fanout(cur, build_anomaly_event(_anomaly())) == 0


# ── 전달 보장(실측 회귀) ─────────────────────────────────────────────────────
class _FakeProducer:
    """flush 후 남는 메시지 수를 흉내낸다 — 토픽 미생성 시 브로커가 보이는 거동."""

    def __init__(self, remaining=0):
        self.remaining, self.sent = remaining, []

    def produce(self, topic, key, value):
        self.sent.append((topic, key, value))

    def poll(self, _):
        pass

    def flush(self, _timeout):
        return self.remaining


def test_emit_raises_when_messages_undelivered():
    """실측 2026-07-29: 토픽이 없으면 produce는 성공한 듯 보이고 flush만 타임아웃한다.
    반환값을 버리면 배치가 '발행 완료'를 찍고 끝나 알림이 통째로 사라진다."""
    import produce_price_anomaly as P

    with pytest.raises(P.DeliveryIncomplete):
        P.emit_anomalies([_anomaly()], prod=_FakeProducer(remaining=1))


def test_emit_succeeds_when_all_delivered():
    import produce_price_anomaly as P

    prod = _FakeProducer(remaining=0)
    assert P.emit_anomalies([_anomaly()], prod=prod) == 1
    assert prod.sent[0][1] == "42"          # key=item_id — 품목별 순서 보장


def test_emit_noop_on_empty():
    """탐지 0건이면 프로듀서를 만들지도 않는다(브로커 연결 불필요)."""
    import produce_price_anomaly as P

    assert P.emit_anomalies([]) == 0
