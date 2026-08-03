"""_price_cache_client 분기(C) — REDIS_SENTINELS 있으면 Sentinel, 없으면 REDIS_URL 폴백.

클라이언트 생성은 지연 연결(첫 명령 시)이라 DB·Redis 없이 분기 선택만 검증한다.
계약 = docs/mp_k8s_redis_ha_handoff.md §7.1 (환경변수 REDIS_SENTINELS/REDIS_MASTER_GROUP/REDIS_URL).
"""
import sys
from pathlib import Path

from redis.sentinel import SentinelConnectionPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from refresh_price_matview import _price_cache_client  # noqa: E402


def test_sentinel_mode_when_sentinels_set(monkeypatch):
    monkeypatch.setenv("REDIS_SENTINELS", "a:26379, b:26379,c:26379,")
    monkeypatch.setenv("REDIS_MASTER_GROUP", "mymaster")
    r = _price_cache_client()
    pool = r.connection_pool
    assert isinstance(pool, SentinelConnectionPool)
    assert pool.service_name == "mymaster"


def test_url_fallback_when_sentinels_absent(monkeypatch):
    monkeypatch.delenv("REDIS_SENTINELS", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    r = _price_cache_client()
    pool = r.connection_pool
    assert not isinstance(pool, SentinelConnectionPool)
    kw = pool.connection_kwargs
    assert (kw["host"], kw["port"]) == ("localhost", 6379)
