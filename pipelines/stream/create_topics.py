"""토픽 생성 (멱등). K8s에선 Strimzi KafkaTopic가 대체 — deploy/k8s/kafka-topics.yaml 참조.
로컬/단일브로커용. retention 7d(경량 가격이력은 PG가 정본, Kafka는 트랜스포트)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _kafka import (admin, PARTITIONS, TOPIC_RETAIL_RAW, TOPIC_DEAL_RAW,   # noqa: E402
                    TOPIC_RECIPE_RAW, TOPIC_USER_ACTIVITY)
from confluent_kafka.admin import NewTopic                # noqa: E402

RETENTION = {"retention.ms": str(7 * 24 * 3600 * 1000), "cleanup.policy": "delete"}


def main():
    a = admin()                          # 참조 유지(임시객체면 future 전 GC → handle destroyed)
    topics = [
        NewTopic(TOPIC_RETAIL_RAW, num_partitions=PARTITIONS, replication_factor=1, config=RETENTION),
        NewTopic(TOPIC_DEAL_RAW, num_partitions=2, replication_factor=1, config=RETENTION),  # 딜=저볼륨
        NewTopic(TOPIC_RECIPE_RAW, num_partitions=PARTITIONS, replication_factor=1, config=RETENTION),
        # 클릭스트림(Track 1) — key=user_id 유저별 순서, PG(activity.user_event)가 정본·Kafka는 트랜스포트.
        NewTopic(TOPIC_USER_ACTIVITY, num_partitions=PARTITIONS, replication_factor=1, config=RETENTION),
    ]
    for topic, fut in a.create_topics(topics).items():
        try:
            fut.result()
            print(f"토픽 생성: {topic}")
        except Exception as e:
            print(f"토픽 {topic}: {e}")   # TopicAlreadyExists 등 멱등 처리


if __name__ == "__main__":
    main()
