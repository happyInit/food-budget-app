"""토픽·파티션 상수 — **드라이버 의존 없음**(순수 env 조회).

`_kafka.py` 는 confluent_kafka 를 임포트하므로, 토픽 이름만 필요한 코드(발행 계약 테스트 등)가
브로커 드라이버까지 설치해야 하는 문제가 있었다. 상수를 여기로 분리해 그 결합을 끊는다.
`_kafka.py` 가 그대로 재수출하므로 기존 `from _kafka import TOPIC_*` 는 전부 유효하다.
"""
import os

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "192.168.0.8:9092")
TOPIC_RETAIL_RAW = os.environ.get("KAFKA_TOPIC_RETAIL", "retail.crawl.raw")
TOPIC_DEAL_RAW = os.environ.get("KAFKA_TOPIC_DEAL", "retail.deal.raw")   # 오아시스 딜(타임/마감세일)
TOPIC_RECIPE_RAW = os.environ.get("KAFKA_TOPIC_RECIPE", "recipe.crawl.raw")   # 만개 레시피(주1회)
# 클릭스트림(Track 1): VIEW·ADD_CART·NOTIF_CLICK. key=user_id(파티션 분산 + 유저별 순서). 설계 §2.
TOPIC_USER_ACTIVITY = os.environ.get("KAFKA_TOPIC_USER_ACTIVITY", "events.user.activity")
# 최저가 이상탐지 → 알림 fan-out(ai-spec §2). 명명 규칙 `도메인.이벤트`를 따른다.
TOPIC_PRICE_ANOMALY = os.environ.get("KAFKA_TOPIC_PRICE_ANOMALY", "price.anomaly.detected")
PARTITIONS = int(os.environ.get("KAFKA_RETAIL_PARTITIONS", "3"))
