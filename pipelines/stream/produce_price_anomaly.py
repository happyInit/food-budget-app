"""최저가 이상탐지 → Kafka 발행 (`ai-spec.md §2` B단계).

탐지 배치(`pipelines/ingest/detect_price_anomaly.py`)가 찾은 급락을 `price.anomaly.detected`로
발행한다. 소비자는 fan-out 컨슈머(`consume_price_anomaly.py`)로, `price.price_watch`를
역조회해 관심 등록 유저에게만 알림을 만든다.

**설계 결정과 근거**
- **key = item_id** — 같은 품목의 이벤트가 한 파티션에 모여 순서가 보장된다. user_id를 키로 쓰면
  같은 품목이 여러 파티션에 흩어져 "어느 소스가 최신인지" 판단이 어려워진다.
- **멱등키 = anomaly_id** — `{item_id}:{source}:{observed_at}`. 배치를 하루 두 번 돌려도 같은
  관측일의 같은 품목·소스는 **한 번만** 알림이 나간다(컨슈머가 이 키로 중복 제거).
- **fire-and-forget 아님** — `flush()`로 전달을 확인한다. 배치는 단발성이라 프로세스가 끝나면
  버퍼가 사라져, 알림이 조용히 유실될 수 있다(클릭스트림과 다른 점).

사용:
    from produce_price_anomaly import emit_anomalies
    emit_anomalies([...])          # detect_price_anomaly.Anomaly 목록(asdict)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# ⚠️ confluent_kafka 임포트는 **지연**한다 — build_anomaly_event 는 순수 함수라
#    드라이버 없이 임포트·테스트할 수 있어야 한다(알림 계약 검증이 인프라에 묶이면 안 된다).
_producer = None


def _topic() -> str:
    from _topics import TOPIC_PRICE_ANOMALY      # 드라이버 없이 토픽명만 — 테스트에서도 임포트된다
    return TOPIC_PRICE_ANOMALY


def _get_producer():
    global _producer
    if _producer is None:
        from _kafka import producer
        _producer = producer("price-anomaly-emitter")   # 멱등·acks=all·전달실패 관측(#558)
    return _producer


def build_anomaly_event(a: dict) -> dict:
    """탐지 결과(dict) → 메시지 계약.

    컨슈머가 알림 문구를 만들 수 있도록 **표시에 필요한 값만** 담는다.
    baseline_std·samples 같은 통계 내부값은 알림에 쓰이지 않으므로 진단용으로만 남긴다.
    """
    return {
        "anomaly_id": f"{a['item_id']}:{a['source']}:{a['observed_at']}",   # 멱등키(사람이 읽는 키)
        # price_anomaly.id — 컨슈머가 price_alert_sent(FK)에 발송 이력을 남기는 데 쓴다.
        # 없으면(미영속 발행) 컨슈머는 쿨다운만으로 중복을 막는다.
        "anomaly_db_id": a.get("db_id"),
        "item_id": a["item_id"],
        "canonical_name": a["canonical_name"],
        "source": a["source"],
        "observed_at": a["observed_at"],
        "price_100g": a["price_100g"],
        "baseline_mean": a["baseline_mean"],
        "drop_pct": a["drop_pct"],
        "is_record_low": a["is_record_low"],
        "discount_rate": a.get("discount_rate"),
        # 진단용 — 알림 문구에는 쓰지 않는다(신뢰도 추적·임계 튜닝 신호).
        "z_score": a["z_score"],
        "samples": a["samples"],
    }


class DeliveryIncomplete(RuntimeError):
    """flush 후에도 전달되지 않은 메시지가 남았다 — 그만큼 알림이 나가지 않는다."""


def emit_anomalies(anomalies: list[dict], prod=None) -> int:
    """이상 목록을 발행하고 건수를 돌려준다. prod 주입 가능(테스트).

    미전달이 남으면 DeliveryIncomplete — 배치가 "발행 완료"로 끝나면 안 된다.
    """
    if not anomalies:
        return 0
    p = prod or _get_producer()
    for a in anomalies:
        ev = build_anomaly_event(a)
        p.produce(_topic(), key=str(ev["item_id"]), value=json.dumps(ev, ensure_ascii=False).encode())
        p.poll(0)
    flush(prod=p)      # 배치는 단발성 — 버퍼에 남으면 알림이 조용히 유실된다
    return len(anomalies)


def flush(timeout: float = 10.0, prod=None) -> None:
    """전달 완료까지 대기. **남은 메시지가 있으면 예외** — 조용히 넘어가지 않는다.

    실측(2026-07-29): 브로커가 `auto.create.topics.enable=false` 라 토픽이 없으면 produce 는
    성공한 것처럼 보이고 flush 만 타임아웃한다. 반환값을 버리면 배치는 "발행 완료"를 출력하고
    끝나 알림이 통째로 사라진다 — 토픽 미생성이 조용한 장애가 되는 지점이라 반드시 드러낸다.

    🔴 **그 방어는 절반이었다** (#558). flush 는 "아직 큐에 남았나"만 세므로
    `delivery.timeout.ms` 만료로 **영구 실패한 메시지는 remaining 0 으로 보인다.**
    (실측 2026-08-09: 닿지 않는 브로커로 3건 → flush remaining **0**, 콜백은 3건 전부 실패)
    그래서 delivery report 실패 건수를 함께 본다.
    """
    from _delivery import tracker              # noqa: PLC0415 — 드라이버 없는 테스트 경로 보존
    p = prod or _producer
    if p is None:
        return
    remaining = p.flush(timeout)
    # 이 배치는 단발 프로세스라 **누적 실패 = 이번 회차 실패**다(기준선을 따로 둘 필요가 없다).
    failed = tracker().failed
    if remaining or failed:
        raise DeliveryIncomplete(
            f"{remaining}건 미전달·{failed}건 전달실패({timeout}s 대기) — "
            f"토픽 {_topic()!r} 존재 여부와 브로커 연결을 확인하라. "
            "토픽 생성: python pipelines/stream/create_topics.py (K8s는 Strimzi KafkaTopic)"
        )
