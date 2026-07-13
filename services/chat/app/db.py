"""PG/ES/Redis 비동기 클라이언트. FastAPI lifespan에서 열고 닫는다(app/main.py)."""
from __future__ import annotations

from elasticsearch import AsyncElasticsearch
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from app.config import settings


def make_pg_pool() -> AsyncConnectionPool:
    conninfo = (
        f"host={settings.pghost} port={settings.pgport} "
        f"dbname={settings.pgdatabase} user={settings.pguser} password={settings.pgpassword}"
    )
    # open=False: lifespan에서 명시적으로 await pool.open() — 생성자에서 즉시 연결 시도 안 함
    return AsyncConnectionPool(conninfo, min_size=1, max_size=5, open=False)


def make_es_client() -> AsyncElasticsearch:
    return AsyncElasticsearch(f"http://{settings.eshost}:{settings.esport}")


def make_redis_client() -> Redis:
    return Redis(host=settings.redishost, port=int(settings.redisport), decode_responses=True)
