"""price-anomaly-notifier 컨슈머: Kafka price.anomaly.detected → notify.notification(LOW_PRICE).

`ai-spec.md §2` C단계 — 탐지된 급락을 **관심 등록(price.price_watch)한 유저에게만** 알림으로 만든다.

**왜 이 컨슈머가 필요한가**
`notify` 서비스는 알림을 *읽기만* 한다(`GET /api/notifications`). 지금까지 `notify.notification`에
행을 넣는 주체가 하나도 없어 목록이 항상 비어 있었다. 이 컨슈머가 첫 writer다.

**노출 정책**(팀 결정 2026-07-28, `ai-spec.md §2` 표)
1. 탐지 배치가 **TOP_N=20**건으로 이미 상한을 건다 — 여기서 다시 자르지 않는다.
2. **유저별 일일 상한 없음** — 관심 신청한 품목만 알리므로 피로도가 구조적으로 낮다.
3. **재알림 쿨다운 7일** — 같은 유저·같은 품목은 7일 내 재알림하지 않는다. 세일이 며칠
   이어지면 배치가 매일 같은 급락을 탐지하는데, 그대로 두면 같은 알림이 매일 나간다.

쿨다운은 **멱등성도 겸한다** — 배치를 재실행하거나 컨슈머가 오프셋을 되감아 같은 메시지를
다시 읽어도, 7일 안에 이미 보낸 알림이 있으면 건너뛴다(at-least-once 전제에서 중복 발송 방지).

env CONSUME_IDLE_EXIT=초 → backlog 소진 후 종료(배치성 실행). 미설정 시 상주.
"""
import json
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))

# ⚠️ Kafka·PG·메트릭 임포트는 main() 안에서 한다 — 아래 정책 함수(build_notification·fanout)는
#    유저에게 나가는 알림을 결정하므로 **드라이버 없이도 테스트**할 수 있어야 한다.
#    다른 컨슈머는 모듈 상단에서 임포트하지만, 여기선 검증 가능성을 우선한다.

GROUP = "price-anomaly-notifier"
COMMIT_EVERY = 100
COOLDOWN_DAYS = 7      # 재알림 쿨다운(팀 결정) — 위 "노출 정책" ③
IDLE_EXIT = float(os.environ["CONSUME_IDLE_EXIT"]) if os.environ.get("CONSUME_IDLE_EXIT") else None

# 관심 등록한 유저 중 **알림을 켜 두고 + 쿨다운이 지난** 유저에게만 알림을 만든다.
# INSERT ... SELECT 한 방으로 처리해 "조회 후 삽입" 사이의 경쟁을 없앤다(컨슈머 다중 실행 대비).
# payload에 item_id를 넣어 두면 프론트가 알림 → 품목 상세로 딥링크할 수 있고,
# 쿨다운 조회도 이 값을 그대로 쓴다.
#
# LEFT JOIN + COALESCE(true): notification_setting 행이 없는 유저는 기본 수신(DDL 기본값과 동일).
# 설정을 끈 유저에게 보내면 관심 등록 여부와 무관하게 사용자 의사를 어기는 것이라 반드시 건다.
_FANOUT_SQL = """
INSERT INTO notify.notification (user_id, type, title, body, payload)
SELECT w.user_id, 'LOW_PRICE', %(title)s, %(body)s, %(payload)s::jsonb
  FROM price.price_watch w
  LEFT JOIN notify.notification_setting s ON s.user_id = w.user_id
 WHERE w.item_id = %(item_id)s
   AND COALESCE(s.low_price, true)
   AND NOT EXISTS (
       SELECT 1 FROM notify.notification n
        WHERE n.user_id = w.user_id
          AND n.type = 'LOW_PRICE'
          AND n.payload->>'item_id' = %(item_id_text)s
          AND n.created_at > now() - make_interval(days => %(cooldown)s)
   )
"""

# db_id 가 있는 이벤트용 — 알림 생성과 발송 이력을 **한 문장(CTE)** 으로 묶는다.
# 두 문장으로 나누면 사이에서 죽었을 때 알림만 남고 이력이 비어 재처리 시 중복 발송된다.
#
# 방어선이 둘인 이유:
#   · price_alert_sent PK — **같은 이상치의 재전달**을 막는다(Kafka at-least-once).
#   · 7일 쿨다운 — **다른 이상치라도 같은 품목**이면 막는다(알림 피로도, 팀 결정).
# 둘은 겹치지 않는다. 쿨다운만 있으면 8일째 재전달된 옛 이벤트가 다시 나가고,
# PK만 있으면 매일 새로 탐지된 같은 품목이 매일 나간다.
#
# ⚠️ `EXISTS (price_anomaly)` 가드가 왜 필요한가 — **실측으로 확인한 크래시 경로**(백로그 §1.5).
#   FK `price_alert_sent.anomaly_id → price_anomaly(id)` 는 `ON DELETE CASCADE` 라 기존 행
#   삭제는 처리하지만, **이미 사라진 행을 참조하는 INSERT 는 그대로 위반**이다:
#       ERROR: violates foreign key constraint "price_alert_sent_anomaly_id_fkey"
#       DETAIL: Key (anomaly_id)=(...) is not present in table "price_anomaly".
#   Kafka retention(7일) 이 이상치 정리 주기보다 길면 **옛 메시지가 사라진 행을 참조**하고,
#   컨슈머에 DLQ 가 없어(#252) 같은 메시지에서 무한 크래시 루프가 된다.
#   → 가드가 있으면 대상 0행이 되어 **조용히 건너뛴다**(fanout 이 0 을 반환 → 로그로 드러남).
#   예외 처리로 잡지 않는 이유: FK 위반은 트랜잭션을 abort 시키므로 같은 배치의
#   **다른 정상 이벤트까지 함께 죽는다.** 사전 가드가 유일하게 안전한 위치다.
_FANOUT_SQL_TRACKED = """
WITH created AS (
  INSERT INTO notify.notification (user_id, type, title, body, payload)
  SELECT w.user_id, 'LOW_PRICE', %(title)s, %(body)s, %(payload)s::jsonb
    FROM price.price_watch w
    LEFT JOIN notify.notification_setting s ON s.user_id = w.user_id
   WHERE w.item_id = %(item_id)s
     AND COALESCE(s.low_price, true)
     AND EXISTS (SELECT 1 FROM price_anomaly pa WHERE pa.id = %(anomaly_db_id)s)
     AND NOT EXISTS (
         SELECT 1 FROM notify.notification n
          WHERE n.user_id = w.user_id
            AND n.type = 'LOW_PRICE'
            AND n.payload->>'item_id' = %(item_id_text)s
            AND n.created_at > now() - make_interval(days => %(cooldown)s)
     )
     AND NOT EXISTS (
         SELECT 1 FROM price_alert_sent a
          WHERE a.anomaly_id = %(anomaly_db_id)s AND a.user_id = w.user_id
     )
  RETURNING id, user_id
)
INSERT INTO price_alert_sent (anomaly_id, user_id, notification_id)
SELECT %(anomaly_db_id)s, user_id, id FROM created
ON CONFLICT (anomaly_id, user_id) DO NOTHING
"""


def build_notification(ev: dict) -> tuple[str, str]:
    """이벤트 → (제목, 본문). 유저가 알림 목록에서 **이것만 보고** 살지 말지 판단할 수 있어야 한다."""
    name = ev.get("canonical_name") or "관심 품목"
    drop = round(float(ev.get("drop_pct") or 0))
    price = float(ev.get("price_100g") or 0)
    mean = float(ev.get("baseline_mean") or 0)
    title = f"{name} 지금 역대 최저가" if ev.get("is_record_low") else f"{name} {drop}% 급락"
    body = (f"100g당 {price:,.0f}원 (최근 평균 {mean:,.0f}원 대비 {drop}%↓) · {ev.get('source', '')}").strip(" ·")
    return title, body


def fanout(cur, ev: dict) -> int:
    """이벤트 1건을 관심 유저에게 확산. 생성된 알림 수를 돌려준다(0=관심 유저 없음/전원 쿨다운)."""
    title, body = build_notification(ev)
    payload = {
        "item_id": ev["item_id"], "source": ev.get("source"),
        "price_100g": ev.get("price_100g"), "drop_pct": ev.get("drop_pct"),
        "is_record_low": ev.get("is_record_low"), "observed_at": ev.get("observed_at"),
        "anomaly_id": ev.get("anomaly_id"),        # 추적용 — 어느 탐지에서 나온 알림인지
    }
    params = {
        "title": title, "body": body, "payload": json.dumps(payload, ensure_ascii=False),
        "item_id": ev["item_id"], "item_id_text": str(ev["item_id"]), "cooldown": COOLDOWN_DAYS,
    }
    db_id = ev.get("anomaly_db_id")
    if db_id is None:
        # 근거가 영속되지 않은 이벤트(구버전·수동 발행) — 쿨다운만으로 중복을 막는다.
        cur.execute(_FANOUT_SQL, params)
    else:
        cur.execute(_FANOUT_SQL_TRACKED, {**params, "anomaly_db_id": db_id})
    return cur.rowcount or 0


def main():
    from _kafka import consumer, producer, TOPIC_PRICE_ANOMALY
    from _db import connect
    from _metrics import (LAST_SUCCESS, PROCESSING_SECONDS, RECORDS, SINK_WRITES,
                          start_metrics_server)
    from _observability import get_pipeline_logger
    from _dlq import quarantine, record_savepoint, summary   # poison 격리(#252)

    log = get_pipeline_logger(GROUP)
    start_metrics_server(GROUP)
    c = consumer(GROUP)
    c.subscribe([TOPIC_PRICE_ANOMALY])
    conn = connect()
    cur = conn.cursor()
    # poison 격리용(#252). librdkafka 지연 연결이라 여기서 브로커에 붙지 않는다.
    dlq = producer(GROUP)          # DLQ 발행용 — 전달실패 로그에 컨슈머 이름이 붙는다(#558)

    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    n = notified = pending = 0
    idle = 0.0

    def commit_pending(count):
        if not count:
            return
        conn.commit()
        c.commit()

    try:
        while running:
            msg = c.poll(1.0)
            if msg is None:
                idle += 1.0
                if pending:
                    commit_pending(pending); pending = 0
                if IDLE_EXIT and idle >= IDLE_EXIT:
                    break
                continue
            if msg.error():
                RECORDS.labels(GROUP, "kafka_error").inc()
                log.warning(
                    "kafka consumer returned an error",
                    extra={"event": "kafka_consume_failed", "component": GROUP,
                           "topic": TOPIC_PRICE_ANOMALY, "consumer_group": GROUP,
                           "error_type": "KafkaMessageError", "error_code": msg.error().code(),
                           "retryable": True},
                )
                continue
            idle = 0.0
            started = time.perf_counter()
            try:
                # savepoint — 제약 위반은 트랜잭션을 abort 시킨다. 그냥 rollback 하면 **같은 배치의
                # 앞선 정상 레코드까지** 사라지고(오프셋은 뒤에 커밋) 조용히 유실된다(#252).
                with record_savepoint(cur):
                    ev = json.loads(msg.value())
                    made = fanout(cur, ev)
            except Exception as exc:
                RECORDS.labels(GROUP, "failure").inc()
                SINK_WRITES.labels(GROUP, "postgres", "failure").inc()
                log.exception(
                    "price anomaly fan-out failed",
                    extra={"event": "pipeline_record_rejected", "component": GROUP,
                           "topic": TOPIC_PRICE_ANOMALY, "consumer_group": GROUP,
                           "error_type": type(exc).__name__, "retryable": False},
                )
                # 영구 실패(payload 파손·제약 위반)면 DLQ 로 격리하고 진행 · 일시 실패는 raise(#252).
                # ⚠️ 이 컨슈머의 FK 위반은 `_FANOUT_SQL_TRACKED` 의 사전 EXISTS 가드가 이미 막는다.
                #    DLQ 는 **그 가드가 모르는 실패**를 위한 뒤층이다(둘은 대체재가 아니다).
                if not quarantine(dlq, msg, exc, GROUP, TOPIC_PRICE_ANOMALY):
                    raise
                log.warning(summary(msg, exc, TOPIC_PRICE_ANOMALY),
                            extra={"event": "pipeline_record_quarantined", "component": GROUP,
                                   "topic": TOPIC_PRICE_ANOMALY, "consumer_group": GROUP,
                                   "error_type": type(exc).__name__, "retryable": False})
                RECORDS.labels(GROUP, "dlq").inc()
                pending += 1     # 🔴 오프셋이 전진해야 루프가 풀린다(continue 금지 — finally 중복)
            else:
                RECORDS.labels(GROUP, "success").inc()
                SINK_WRITES.labels(GROUP, "postgres", "success").inc()
                notified += made
                n += 1; pending += 1
            finally:
                PROCESSING_SECONDS.labels(GROUP).observe(time.perf_counter() - started)
            if pending >= COMMIT_EVERY:
                commit_pending(pending); pending = 0
        if pending:
            commit_pending(pending)
    finally:
        cur.close(); conn.close(); c.close()
    LAST_SUCCESS.labels(GROUP).set(time.time())
    log.info(
        "price anomaly notifier stopped",
        extra={"event": "pipeline_stopped", "component": GROUP, "records": n,
               "notifications": notified},
    )


if __name__ == "__main__":
    main()
