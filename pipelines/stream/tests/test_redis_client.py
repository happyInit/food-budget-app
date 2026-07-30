"""_redis.client() 분기(C) — REDIS_SENTINELS 있으면 Sentinel, 없으면 REDIS_URL 폴백.

클라이언트 생성은 지연 연결(첫 명령 시)이라 Redis 없이 분기 선택만 검증한다.
계약 = docs/mp_k8s_redis_ha_handoff.md §7.1 (환경변수 REDIS_SENTINELS/REDIS_MASTER_GROUP/REDIS_URL).
"""
import sys
from pathlib import Path

from redis.sentinel import SentinelConnectionPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _redis  # noqa: E402


def test_parse_sentinels_enumerates_all_pods():
    # 공백·트레일링 콤마 허용 — ConfigMap 값 편집 실수에 관대하게.
    spec = "mp-redis-s-0.mp-redis-s-hl.data.svc:26379, mp-redis-s-1.mp-redis-s-hl.data.svc:26379,"
    assert _redis._parse_sentinels(spec) == [
        ("mp-redis-s-0.mp-redis-s-hl.data.svc", 26379),
        ("mp-redis-s-1.mp-redis-s-hl.data.svc", 26379),
    ]


def test_sentinel_mode_when_sentinels_set(monkeypatch):
    monkeypatch.setattr(_redis, "REDIS_SENTINELS", "a:26379,b:26379,c:26379")
    monkeypatch.setattr(_redis, "REDIS_MASTER_GROUP", "mymaster")
    r = _redis.client()
    pool = r.connection_pool
    assert isinstance(pool, SentinelConnectionPool)
    assert pool.service_name == "mymaster"


def test_url_fallback_when_sentinels_absent(monkeypatch):
    monkeypatch.setattr(_redis, "REDIS_SENTINELS", "")
    monkeypatch.setattr(_redis, "REDIS_URL", "redis://192.168.0.8:6379/0")
    r = _redis.client()
    pool = r.connection_pool
    assert not isinstance(pool, SentinelConnectionPool)
    kw = pool.connection_kwargs
    assert (kw["host"], kw["port"]) == ("192.168.0.8", 6379)
