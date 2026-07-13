"""Redis 핫딜 저장 (design.md §7.1 딜 → PG + Redis · §8.2 핫딜 fan-out).
활성 딜 = ZSET retail:deals:active (member=source:product_id, score=마감 epoch ms) → API가 마감임박 조회.
상세 = HASH retail:deals:detail (member → json). 마감 지난 것은 프루닝(zremrangebyscore)."""
import json
import os
import time

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://192.168.0.8:6379/0")
ZSET_ACTIVE = "retail:deals:active"
HASH_DETAIL = "retail:deals:detail"


def client():
    return redis.Redis.from_url(REDIS_URL, socket_timeout=5, decode_responses=True)


def push_deal(r, source, rec, item_id=None):
    """딜 레코드 → Redis 활성딜 등록(멱등, product 단위). 반환 (key, 마감 score)."""
    key = f"{source}:{rec.get('product_id')}"
    end = rec.get("timedeal_end") or int((time.time() + 6 * 3600) * 1000)   # 타이머 없으면 +6h 폴백
    detail = json.dumps({"name": rec.get("name"), "price": rec.get("price"), "item_id": item_id,
                         "deal_type": rec.get("deal_type"), "timedeal_end": rec.get("timedeal_end"),
                         "url": rec.get("url")}, ensure_ascii=False)
    pipe = r.pipeline()
    pipe.zadd(ZSET_ACTIVE, {key: end})
    pipe.hset(HASH_DETAIL, key, detail)
    pipe.execute()
    return key, end


def prune_expired(r, now_ms=None):
    """마감 지난 딜 제거. 반환 제거 수."""
    now_ms = now_ms or int(time.time() * 1000)
    expired = r.zrangebyscore(ZSET_ACTIVE, 0, now_ms)
    if expired:
        pipe = r.pipeline()
        pipe.zremrangebyscore(ZSET_ACTIVE, 0, now_ms)
        pipe.hdel(HASH_DETAIL, *expired)
        pipe.execute()
    return len(expired)
