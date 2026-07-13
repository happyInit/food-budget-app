"""Kafka 공통 설정 (design.md §7.1 수집 파이프라인).
브로커=env KAFKA_BOOTSTRAP(기본 192.168.0.8:9092, fb-data VM). confluent-kafka.
토픽 retail.crawl.raw: 컬리·오아시스 크롤 원본. key=source:product_id(파티션·순서), 헤더 source.
"""
import os

from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "192.168.0.8:9092")
TOPIC_RETAIL_RAW = os.environ.get("KAFKA_TOPIC_RETAIL", "retail.crawl.raw")
TOPIC_DEAL_RAW = os.environ.get("KAFKA_TOPIC_DEAL", "retail.deal.raw")   # 오아시스 딜(타임/마감세일)
PARTITIONS = int(os.environ.get("KAFKA_RETAIL_PARTITIONS", "3"))


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
