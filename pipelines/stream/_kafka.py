"""Kafka 공통 설정 (design.md §7.1 수집 파이프라인).
브로커=env KAFKA_BOOTSTRAP(기본 192.168.0.8:9092, fb-data VM). confluent-kafka.
토픽 retail.crawl.raw: 컬리·오아시스 크롤 원본. key=source:product_id(파티션·순서), 헤더 source.
"""
from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient

# 토픽·브로커 상수는 드라이버 없는 _topics 에 있다(테스트가 confluent_kafka 없이 임포트 가능).
# 재수출 — 기존 `from _kafka import TOPIC_*` 호출부는 그대로 동작한다.
from _topics import (BOOTSTRAP, PARTITIONS, TOPIC_DEAL_RAW,  # noqa: F401
                     TOPIC_PRICE_ANOMALY, TOPIC_RECIPE_RAW,
                     TOPIC_RETAIL_RAW, TOPIC_USER_ACTIVITY)


def producer():
    # 멱등 프로듀서(중복·순서 보장) + acks=all. 저볼륨이라 배치는 linger로만.
    return Producer({
        "bootstrap.servers": BOOTSTRAP,
        "enable.idempotence": True,
        "acks": "all",
        "linger.ms": 50,
        "client.id": "retail-poller",
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
