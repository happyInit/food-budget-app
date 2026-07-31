"""make_redis_client 분기(C) — REDIS_SENTINELS 있으면 Sentinel, 없으면 단일 호스트 폴백.

클라이언트 생성은 지연 연결(첫 명령 시)이라 DB·Redis 없이 분기 선택만 검증한다.
계약 = docs/mp_k8s_redis_ha_handoff.md §7.1 (환경변수 REDIS_SENTINELS/REDIS_MASTER_GROUP/REDIS_URL).
"""
from redis.asyncio.sentinel import SentinelConnectionPool

from app.config import settings
from app.db import _parse_sentinels, make_redis_client


def test_parse_sentinels_enumerates_all_pods():
    # 공백·트레일링 콤마 허용 — ConfigMap 값 편집 실수에 관대하게.
    spec = "mp-redis-s-0.mp-redis-s-hl.data.svc:26379, mp-redis-s-1.mp-redis-s-hl.data.svc:26379,"
    assert _parse_sentinels(spec) == [
        ("mp-redis-s-0.mp-redis-s-hl.data.svc", 26379),
        ("mp-redis-s-1.mp-redis-s-hl.data.svc", 26379),
    ]


def test_sentinel_mode_when_sentinels_set(monkeypatch):
    monkeypatch.setattr(settings, "redis_sentinels", "a:26379,b:26379,c:26379")
    monkeypatch.setattr(settings, "redis_master_group", "mymaster")
    client = make_redis_client()
    pool = client.connection_pool
    assert isinstance(pool, SentinelConnectionPool)
    assert pool.service_name == "mymaster"


def test_single_host_fallback_when_sentinels_absent(monkeypatch):
    monkeypatch.setattr(settings, "redis_sentinels", "")
    client = make_redis_client()
    pool = client.connection_pool
    assert not isinstance(pool, SentinelConnectionPool)
    kw = pool.connection_kwargs
    assert (kw["host"], kw["port"]) == (settings.redishost, int(settings.redisport))
