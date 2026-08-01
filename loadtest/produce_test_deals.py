# Stage2B — 합성 TEST- 딜 프로듀서 (파이프라인 파드 안에서 실행)
# retail.deal.raw 에 TEST- timeSale 딜 N건 발행 → Kafka lag → KEDA가 mp-deal-notifier 깨움.
# product_id 는 TEST-DEAL-* → purge_loadtest_seed.py 로 정리 가능.
# 실행(파드 내): python /tmp/prod.py 5000
import sys
sys.path.insert(0, '/app/pipelines/stream')
import json
from _kafka import producer, TOPIC_DEAL_RAW

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
p = producer()
for i in range(N):
    rec = {
        "source": "oasis",
        "product_id": "TEST-DEAL-%d" % i,
        "url": "http://loadtest.invalid/%d" % i,
        "name": "LOADTEST deal %d" % i,
        "image_url": "http://loadtest.invalid/img",
        "category_id": 11, "l": "general",
        "crawled_at": "2026-08-01T14:00:00+09:00",
        "price": 1000 + (i % 5000),
        "deal_type": "timeSale",
        "timedeal_end": "2026-08-01T23:59:59+09:00",
        "volume_text": "200g", "weight_g": 200,
        "unit_price": 500, "unit_basis": "100g",
        "storage": "COLD", "expiry_text": None, "origin": "KR",
        "is_fresh_seasonal": False, "delivery_types": ["dawn"],
        "is_sold_out": False,
    }
    p.produce(TOPIC_DEAL_RAW,
              key=("oasis:TEST-DEAL-%d" % i).encode(),
              value=json.dumps(rec).encode(),
              headers=[("source", b"oasis")])
    if i % 500 == 0:
        p.poll(0)
p.flush()
print("produced", N, "TEST- deals to", TOPIC_DEAL_RAW)
