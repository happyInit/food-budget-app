"""PG/ES/Redis 비동기 클라이언트. FastAPI lifespan에서 열고 닫는다(app/main.py)."""
from __future__ import annotations

from elasticsearch import AsyncElasticsearch
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis
from redis.asyncio.sentinel import Sentinel

from app.config import settings


def make_pg_pool() -> AsyncConnectionPool:
    conninfo = (
        f"host={settings.pghost} port={settings.pgport} "
        f"dbname={settings.pgdatabase} user={settings.pguser} password={settings.pgpassword} "
        # statement_timeout: 느린 쿼리가 커넥션을 무한 점유 못 하게 서버측 상한(초과 시 취소 → 커넥션 반납).
        f"options='-c statement_timeout={settings.pg_statement_timeout_ms}'"
    )
    # open=False: lifespan에서 명시적으로 await pool.open() — 생성자에서 즉시 연결 시도 안 함
    # check: 체크아웃 시 죽은 커넥션 검사 후 재연결 — 원격 PG가 idle 커넥션을 끊어도
    # "server closed the connection unexpectedly" 500 대신 정상 재연결(간헐 실패 방지).
    return AsyncConnectionPool(
        conninfo, min_size=settings.pg_pool_min, max_size=settings.pg_pool_max, open=False,
        check=AsyncConnectionPool.check_connection,
    )


def make_es_client() -> AsyncElasticsearch:
    # request_timeout: 느린 ES 검색이 응답을 무한 대기하지 않게 상한(초과 시 예외 → 소스 degrade).
    # basic_auth: ECK(P2)는 인증 강제. env 없으면 생략 — 현행 VM ES(무인증) 동작 불변.
    # 스킴이 http 인 것은 의도다 — HTTP TLS 는 끄고 암호화는 WireGuard 가 맡는다(플랜 §6.2).
    auth = (settings.es_user, settings.es_password) if settings.es_user else None
    return AsyncElasticsearch(f"http://{settings.eshost}:{settings.esport}",
                              basic_auth=auth,
                              request_timeout=settings.es_request_timeout_s)


def _parse_sentinels(spec: str) -> list[tuple[str, int]]:
    """"host:port,host:port" → [(host, port), …]. sentinel 파드 3개를 전부 열거한다(단일 DNS 금지)."""
    return [(h, int(p)) for h, p in (e.strip().rsplit(":", 1) for e in spec.split(",") if e.strip())]


def make_redis_client() -> Redis:
    # REDIS_SENTINELS 있으면 Sentinel 모드(분기 C) — 노드 상실 국면에서 master Service 가 갱신되지
    # 않으므로 Service 가 아니라 Sentinel 에게 master 를 묻는다(docs/mp_k8s_redis_ha_handoff.md §4).
    # env 없으면 기존 단일 호스트 경로 — 현행 VM(.8) 동작 불변(위 ES basic_auth 와 같은 하위호환 패턴).
    if settings.redis_sentinels:
        return Sentinel(_parse_sentinels(settings.redis_sentinels)).master_for(
            settings.redis_master_group, decode_responses=True)
    return Redis(host=settings.redishost, port=int(settings.redisport), decode_responses=True)
