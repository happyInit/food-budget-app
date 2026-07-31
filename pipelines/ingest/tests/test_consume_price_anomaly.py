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


# ── 발송 이력(price_alert_sent) — 재전달 방어 ────────────────────────────────
def test_tracked_fanout_records_alert_history():
    """db_id 가 있으면 알림 생성과 발송 이력을 한 문장으로 묶는다.

    두 문장으로 나누면 사이에서 죽었을 때 알림만 남고 이력이 비어, 재처리 시 같은
    유저에게 또 나간다.
    """
    m = _load_consumer()
    cur = _FakeCur()
    ev = build_anomaly_event(_anomaly())
    ev["anomaly_db_id"] = 77
    m.fanout(cur, ev)

    assert "price_alert_sent" in cur.sql
    assert "WITH created AS" in cur.sql          # 한 문장(CTE)
    assert "ON CONFLICT (anomaly_id, user_id) DO NOTHING" in cur.sql
    assert cur.params["anomaly_db_id"] == 77


def test_tracked_fanout_has_both_defenses():
    """재전달(PK)과 알림 피로도(쿨다운)는 서로 다른 실패를 막는다 — 둘 다 있어야 한다."""
    m = _load_consumer()
    cur = _FakeCur()
    ev = build_anomaly_event(_anomaly())
    ev["anomaly_db_id"] = 77
    m.fanout(cur, ev)

    assert "price_alert_sent a" in cur.sql       # 같은 이상치 재전달 차단
    assert "make_interval(days => %(cooldown)s)" in cur.sql   # 같은 품목 7일 차단


def test_untracked_event_falls_back_to_cooldown_only():
    """근거가 영속되지 않은 이벤트는 FK 를 쓸 수 없다 — 쿨다운만으로 동작해야 한다."""
    m = _load_consumer()
    cur = _FakeCur()
    ev = build_anomaly_event(_anomaly())         # anomaly_db_id 없음(None)
    m.fanout(cur, ev)

    assert "price_alert_sent" not in cur.sql
    assert "make_interval(days => %(cooldown)s)" in cur.sql


def test_event_carries_db_id_when_persisted():
    """탐지 배치가 영속 후 발행하면 이벤트에 price_anomaly.id 가 실린다."""
    ev = build_anomaly_event({**_anomaly(), "db_id": 42})
    assert ev["anomaly_db_id"] == 42
    assert build_anomaly_event(_anomaly())["anomaly_db_id"] is None


def test_fanout_guards_against_deleted_anomaly_row():
    """이상치 행이 사라진 뒤 옛 Kafka 메시지가 와도 **컨슈머가 죽지 않아야** 한다(백로그 §1.5).

    FK `price_alert_sent.anomaly_id → price_anomaly(id)` 는 ON DELETE CASCADE 라 기존 행
    삭제는 처리하지만, **없어진 행을 참조하는 INSERT 는 그대로 위반**이다. 운영 PG 에서 실측:

        ERROR: violates foreign key constraint "price_alert_sent_anomaly_id_fkey"
        DETAIL: Key (anomaly_id)=(-999999) is not present in table "price_anomaly".

    Kafka retention(7일)이 이상치 정리 주기보다 길면 이 경로가 열리고, 컨슈머에 DLQ 가
    없어(#252) 같은 메시지에서 무한 크래시 루프가 된다. 사전 EXISTS 가드로 막는다 —
    예외 처리로는 안 된다(FK 위반은 트랜잭션을 abort 시켜 같은 배치의 정상 이벤트까지 죽는다).

    운영 PG 실측(모듈 원문 SQL): 이상치 존재 → INSERT 0 1 · 삭제 후 → INSERT 0 0 (에러 없음).
    """
    m = _load_consumer()
    cur = _FakeCur()
    ev = {**build_anomaly_event(_anomaly()), "anomaly_db_id": 7}
    m.fanout(cur, ev)
    assert "EXISTS (SELECT 1 FROM price_anomaly" in cur.sql   # 가드가 SQL 에 있어야
    assert cur.params["anomaly_db_id"] == 7

    # db_id 가 없는 이벤트(구버전·수동 발행)는 추적 SQL 을 타지 않으므로 가드도 무관하다
    cur2 = _FakeCur()
    m.fanout(cur2, build_anomaly_event(_anomaly()))
    assert "price_alert_sent" not in cur2.sql
