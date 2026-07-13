"""토픽 생성 (멱등). K8s에선 Strimzi KafkaTopic가 대체 — deploy/k8s/kafka-topics.yaml 참조.
로컬/단일브로커용. retention 7d(경량 가격이력은 PG가 정본, Kafka는 트랜스포트)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _kafka import admin, PARTITIONS, TOPIC_RETAIL_RAW   # noqa: E402
from confluent_kafka.admin import NewTopic                # noqa: E402


def main():
    a = admin()                          # 참조 유지(임시객체면 future 전 GC → handle destroyed)
    topics = [NewTopic(TOPIC_RETAIL_RAW, num_partitions=PARTITIONS, replication_factor=1,
                       config={"retention.ms": str(7 * 24 * 3600 * 1000),
                               "cleanup.policy": "delete"})]
    for topic, fut in a.create_topics(topics).items():
        try:
            fut.result()
            print(f"토픽 생성: {topic} (partitions={PARTITIONS})")
        except Exception as e:
            print(f"토픽 {topic}: {e}")   # TopicAlreadyExists 등 멱등 처리


if __name__ == "__main__":
    main()
