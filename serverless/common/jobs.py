"""접수·워커가 공유하는 계약 — 잡 상태 · 단일비행 락 · 큐 전송.

**이 모듈은 새 설계가 아니다.** `services/video/app/store.py` 가 이미 갖고 있는 Valkey 키
계약(잡 1h · 캐시 30일 · 락 `SET NX EX`)을 **그대로** 옮긴 것이고, 거기 없던 **SQS 전송 한 조각**만
더한다. 분할하면서 바뀌는 것은 *"일이 도는 자리"* 뿐이라 계약을 새로 짤 이유가 없다
(`docs/serverless/01_접수-워커_분할설계.md` §1 "이미 있는 것 — 재설계하지 않는다").

🔴 **동기 redis 를 쓴다.** 원본은 `redis.asyncio` 인데 Lambda 핸들러는 이벤트 하나를 처리하고
   끝나므로 이벤트 루프를 세울 이득이 없다. `asyncio.run` 을 매 호출 감싸면 INIT 밖에서
   루프를 만들고 버리는 비용만 남는다.

🔴 **커넥션은 모듈 전역에 둔다.** Lambda 는 같은 실행 환경을 재사용하므로 핸들러마다 새로
   연결하면 warm 호출에서도 TCP+TLS 핸드셰이크를 매번 치른다. 전역에 두면 두 번째 호출부터 공짜다.
"""
from __future__ import annotations

import json
import os
from typing import Any

# 🔴 **키는 각 서비스의 `store.py` 에서 그대로 베껴 온다. 여기서 새로 짓지 않는다.**
#    파드와 Lambda 가 같은 Valkey 를 보는데 키가 갈리면, 이관 도중 접수는 파드가 받고 폴링은
#    Lambda 가 받는 순간 **잡을 못 찾는다**(그 반대도 같다). 형상을 갈라놓을 이유가 없다.
#
# 🔵 `cache`·`lock` 이 없는 네임스페이스가 있다 — **없는 게 맞아서 없다.**
#    video 는 «같은 URL 은 한 번만 분석» 이 성립해 URL 로 캐시·락을 건다. OCR 은 영수증
#    **이미지**가 입력이라 같은 사진을 두 번 올릴 이유가 없고, 실제로 `services/ocr/app/store.py`
#    에도 잡 키 하나뿐이다. 그래서 없는 것을 부르면 **조용히 넘어가지 않고 터진다**(아래 `_key`).
_KEYS: dict[str, dict[str, str]] = {
    # ← services/video/app/store.py
    "video": {"job": "video:job:{}", "cache": "video:recipe:{}", "lock": "video:lock:{}"},
    # ← services/ocr/app/store.py  (_KEY = "ocr:job:{}" · 캐시·락 없음)
    "ocr": {"job": "ocr:job:{}"},
}

# 함수별 환경변수로 고른다. 기본값이 video 인 것은 **기존 두 함수를 안 건드리려는** 것뿐이다.
NS = os.environ.get("JOB_NS", "video")


def _key(kind: str, arg: str) -> str:
    table = _KEYS.get(NS)
    if table is None:
        raise RuntimeError(f"JOB_NS={NS!r} 에 해당하는 키 계약이 없다 — common/jobs.py 에 추가할 것")
    tpl = table.get(kind)
    if tpl is None:
        # 예: OCR 워커가 실수로 `acquire()` 를 부른 경우. no-op 으로 넘기면 «락이 걸린 줄 아는»
        # 코드가 그대로 흘러가 중복 처리를 막지 못한다 — 조용한 성공보다 즉시 실패가 낫다.
        raise RuntimeError(f"JOB_NS={NS!r} 에는 {kind!r} 계약이 없다 — 이 함수를 부르면 안 된다")
    return tpl.format(arg)

JOB_TTL_S = int(os.environ.get("JOB_TTL_S", "3600"))          # 1h — 원본 기본값
CACHE_TTL_S = int(os.environ.get("CACHE_TTL_S", str(30 * 86400)))   # 30일
LOCK_TTL_S = int(os.environ.get("LOCK_TTL_S", "180"))         # 3분 — §3① 의 유일한 방어선

_redis = None
_sqs = None


def redis():
    """Valkey 클라이언트(모듈 캐시). `REDIS_URL` 없으면 host/port 로 조립한다."""
    global _redis
    if _redis is None:
        import redis as _r                      # 지연 import — 큐만 쓰는 함수는 안 불러도 된다

        url = os.environ.get("REDIS_URL")
        if url:
            _redis = _r.Redis.from_url(url, decode_responses=True,
                                       socket_timeout=3, socket_connect_timeout=3)
        else:
            _redis = _r.Redis(
                host=os.environ.get("REDISHOST", "localhost"),
                port=int(os.environ.get("REDISPORT", "6379")),
                decode_responses=True, socket_timeout=3, socket_connect_timeout=3,
            )
    return _redis


def sqs():
    global _sqs
    if _sqs is None:
        import boto3                            # Lambda 런타임 제공 — 번들에 안 넣는다

        _sqs = boto3.client("sqs")
    return _sqs


# ── 잡 상태 ────────────────────────────────────────────────────────────────────
def put_job(job_id: str, payload: dict) -> None:
    redis().set(_key("job", job_id), json.dumps(payload, ensure_ascii=False), ex=JOB_TTL_S)


def get_job(job_id: str) -> dict | None:
    raw = redis().get(_key("job", job_id))
    return json.loads(raw) if raw else None


# ── 결과 캐시 ──────────────────────────────────────────────────────────────────
def get_cached(key: str) -> dict | None:
    raw = redis().get(_key("cache", key))
    return json.loads(raw) if raw else None


def set_cached(key: str, value: dict) -> None:
    redis().set(_key("cache", key), json.dumps(value, ensure_ascii=False), ex=CACHE_TTL_S)


# ── 단일비행 락 ────────────────────────────────────────────────────────────────
def acquire(key: str) -> bool:
    """`SET NX EX` — 원본과 동일. 🔴 **워커 타임아웃을 이 TTL 아래로 둔다.**

    분할 전에는 같은 프로세스라 `finally` 로 해제가 보장됐다. 분할 후 워커가 죽으면 락이 남고,
    그때 **TTL 만이 유일한 방어선**이다. 워커 타임아웃이 TTL 보다 길면 *"락은 풀렸는데 워커는
    아직 도는"* 구간이 생겨 같은 URL 이 중복 분석된다(비용 2배) — 설계서 §3①.
    """
    return bool(redis().set(_key("lock", key), "1", nx=True, ex=LOCK_TTL_S))


def release(key: str) -> None:
    redis().delete(_key("lock", key))


# ── 큐 전송 ────────────────────────────────────────────────────────────────────
def enqueue(queue_url: str, body: dict) -> str:
    """워커 큐로 한 건 보낸다. 본문은 200바이트 수준이라 SQS 상한(256KB)에 여유가 크다."""
    resp = sqs().send_message(QueueUrl=queue_url, MessageBody=json.dumps(body, ensure_ascii=False))
    return resp["MessageId"]


# ── SQS 이벤트 해석 ────────────────────────────────────────────────────────────
def sqs_records(event: Any) -> list[tuple[dict, int]]:
    """SQS 이벤트 → `(본문dict, 수신횟수)` 목록.

    🔴 **수신횟수를 같이 돌려주는 이유** = 마지막 시도를 알아야 하기 때문이다. 분할 후 워커의
       실패는 재시도 뒤 DLQ 로 가는데, 그동안 사용자 잡 상태는 `PENDING` 그대로다 —
       **영원히 기다리게 된다**(설계서 §3③). 마지막 시도에서 `FAILED` 를 남겨야 그게 끊긴다.
    """
    out = []
    for rec in (event or {}).get("Records", []):
        try:
            body = json.loads(rec.get("body") or "{}")
        except json.JSONDecodeError:
            body = {}
        received = int((rec.get("attributes") or {}).get("ApproximateReceiveCount", 1))
        out.append((body, received))
    return out


def is_last_attempt(received: int) -> bool:
    """`MAX_RECEIVE_COUNT`(큐의 maxReceiveCount 와 같은 값)에 도달했나."""
    return received >= int(os.environ.get("MAX_RECEIVE_COUNT", "3"))
