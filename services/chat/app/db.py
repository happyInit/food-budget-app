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
        # prepare_threshold=None: 서버측 prepared statement 비활성. PgBouncer transaction 풀링은
        # 트랜잭션마다 백엔드가 바뀔 수 있어, 켜 두면 `prepared statement "..." does not exist` 가 난다.
        kwargs={"prepare_threshold": None},
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
    #
    # 🔴 소켓 타임아웃(체크리스트 `1-15`) — 없으면 **무한 대기**다. 온프렘에서는 Redis 가 같은
    #    클러스터라 잘 드러나지 않았지만, AWS 는 사이트 간 지연이 생기는 구성이라 그때 터진다.
    #    값은 앱 서비스 선례를 따른다(video·ocr = 3s / pipelines = 5s).
    #    🔴 Sentinel 은 소켓이 **둘**이다 — 센티널에게 master 를 묻는 커넥션 / master 자체 커넥션.
    #    redis-py 는 `sentinel_kwargs` 를 안 주면 `connection_kwargs` 에서 **`socket_` 로 시작하는
    #    키만 자동 복사**해 센티널 쪽에 쓴다(`redis/asyncio/sentinel.py` Sentinel.__init__ 실측).
    #    지금 두 값이 다 `socket_*` 라 양쪽에 걸린다 — ⚠️ 접두사가 다른 옵션을 추가할 땐
    #    `sentinel_kwargs=` 를 명시해야 한다. 선례 = `pipelines/stream/_redis.py:27-28`.
    #
    # 🟡 **켤 때 따라오는 것** — 이 클라이언트를 쓰는 `guardrails.py` 의 상한 3종
    #    (`check_daily_cap`·`incr_monthly_calls`·`monthly_budget_exceeded`)은 전부 **fail-open** 이다.
    #    타임아웃이 있으면 Redis 장애 시 3초 뒤 except 로 떨어져 **상한 없이 통과**한다.
    #
    # 🔴 **다만 현재 노출은 0 이다**(이슈 #642 지적 · 온프렘 ConfigMap 실측):
    #        GENERATOR_BACKEND: "template"   (무료 — LLM 호출 자체가 없다)
    #        RATE_LIMIT_ENABLED: "false"  ·  MONTHLY_CAP_ENABLED: "false"
    #    셋 다 꺼져 있어 **잠재 위험이지 현재 위험이 아니다.** `gemini`/`bedrock` 으로 켤 때 발현된다.
    #    (종전 주석이 이걸 현재 위험처럼 서술했다 — 정정.)
    #
    #    무한 대기 쪽이 더 나쁘다 — 커넥션을 점유해 **서비스 전체를 세운다**. 코드가 명시한
    #    정책도 *"상한은 비용 방어지 서비스 차단이 아님"* 이다. 관련 = 체크리스트 `1-37`.
    timeouts = {"socket_timeout": settings.redis_socket_timeout_s,
                "socket_connect_timeout": settings.redis_socket_timeout_s}
    if settings.redis_sentinels:
        return Sentinel(_parse_sentinels(settings.redis_sentinels), **timeouts).master_for(
            settings.redis_master_group, decode_responses=True, **timeouts)
    return Redis(host=settings.redishost, port=int(settings.redisport),
                 decode_responses=True, **timeouts)
