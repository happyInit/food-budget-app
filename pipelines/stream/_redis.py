"""Redis 핫딜 저장 (design.md §7.1 딜 → PG + Redis · §8.2 핫딜 fan-out).
활성 딜 = ZSET retail:deals:active (member=source:product_id, score=마감 epoch ms) → API가 마감임박 조회.
상세 = HASH retail:deals:detail (member → json). 마감 지난 것은 프루닝(zremrangebyscore)."""
import json
import os
import time

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
# Sentinel 모드(분기 C — K8s): 있으면 Sentinel 에게 master 를 묻는다. 노드 상실 국면에서 master
# Service 가 갱신되지 않아 Service 경로를 못 믿는다(docs/mp_k8s_redis_ha_handoff.md §4).
# 없으면 REDIS_URL 폴백(로컬 개발·단일 Redis 용). 운영은 Sentinel 목록이 주입된다.
REDIS_SENTINELS = os.environ.get("REDIS_SENTINELS", "")
REDIS_MASTER_GROUP = os.environ.get("REDIS_MASTER_GROUP", "mymaster")
ZSET_ACTIVE = "retail:deals:active"
HASH_DETAIL = "retail:deals:detail"


def _parse_sentinels(spec):
    """"host:port,host:port" → [(host, port), …]. sentinel 파드 3개를 전부 열거한다(단일 DNS 금지)."""
    return [(h, int(p)) for h, p in (e.strip().rsplit(":", 1) for e in spec.split(",") if e.strip())]


def client():
    if REDIS_SENTINELS:
        return redis.Sentinel(_parse_sentinels(REDIS_SENTINELS), socket_timeout=5).master_for(
            REDIS_MASTER_GROUP, socket_timeout=5, decode_responses=True)
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
