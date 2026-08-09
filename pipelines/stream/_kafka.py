"""Kafka 공통 설정 (design.md §7.1 수집 파이프라인).
브로커=env KAFKA_BOOTSTRAP. confluent-kafka.
기본값 localhost:9092 는 로컬 개발용 placeholder 다 — 운영값은 mp-pipeline-env 가 주입한다.
토픽 retail.crawl.raw: 컬리·오아시스 크롤 원본. key=source:product_id(파티션·순서), 헤더 source.
"""
from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient

# 토픽·브로커 상수는 드라이버 없는 _topics 에 있다(테스트가 confluent_kafka 없이 임포트 가능).
# 재수출 — 기존 `from _kafka import TOPIC_*` 호출부는 그대로 동작한다.
from _topics import (BOOTSTRAP, PARTITIONS, TOPIC_DEAL_RAW,  # noqa: F401
                     TOPIC_PRICE_ANOMALY, TOPIC_RECIPE_RAW,
                     TOPIC_RETAIL_RAW, TOPIC_USER_ACTIVITY)
from _delivery import DELIVERY_TIMEOUT_MS, tracker


def producer(component=None):
    """멱등 프로듀서(중복·순서 보장) + acks=all. 저볼륨이라 배치는 linger로만.

    🔴 **전달 실패 관측을 팩토리에 내장한다** (#558). 호출부가 콜백 등록을 잊으면 그 프로듀서만
       조용해지는데, 조용한 유실이 바로 이 이슈의 본체다. `on_delivery` 는 config 키로 넣으면
       **produce() 마다 콜백을 넘기지 않아도** 전 메시지에 적용된다(2026-08-09 실측 확인).
       → 이 팩토리를 쓰는 모든 호출부(11곳)가 자동으로 관측 대상이 된다.

    ⚠️ 콜백은 `poll()`/`flush()` 를 호출할 때 실행된다. produce 만 하고 poll/flush 를 한 번도
       안 하면 실패를 못 본다 — 기존 호출부는 전부 둘 중 하나를 하고 있다(마감은 `_delivery.finalize`).
    """
    trk = tracker(component)
    return Producer({
        "bootstrap.servers": BOOTSTRAP,
        "enable.idempotence": True,
        "acks": "all",
        "linger.ms": 50,
        "client.id": component or "retail-poller",
        # 🔴 기본값(300,000ms)과 같은 값을 **명시**한다 — 기본에 기대면 드라이버가 바뀔 때
        #    유실 인내 시간이 조용히 달라진다. 값의 근거·이관 후 재조정은 _delivery 참조.
        "delivery.timeout.ms": DELIVERY_TIMEOUT_MS,
        "on_delivery": trk.on_delivery,
        "error_cb": trk.on_error,
    })


def consumer(group_id):
    # 수동 커밋(at-least-once + DB 멱등 upsert = 사실상 exactly-once at DB).
    return Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "partition.assignment.strategy": "cooperative-sticky",
    })


def admin():
    return AdminClient({"bootstrap.servers": BOOTSTRAP})
