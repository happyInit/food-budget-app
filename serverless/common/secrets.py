"""Secrets Manager → 환경변수 어댑터. **자격증명 경로가 바뀌는 자리는 여기 하나뿐이다.**

**왜 필요한가.** 온프렘 파드는 ESO(External Secrets Operator)가 자격증명을 K8s Secret 으로
풀어 주고 `envFrom` 으로 환경변수로 받는다. **Lambda 에는 ESO 도 `envFrom` 도 없다.**
그래서 함수가 **직접 Secrets Manager 를 호출해** 값을 가져와야 한다.

**그런데 그 아래 코드는 안 바꾼다.** `pipelines/ingest/_db.py` 는 이미 전부 환경변수를 읽는다
(`PGHOST` · `PGPASSWORD` · `ESHOST` · `ES_PASSWORD` …). 그래서 이 모듈이 **부팅 때 한 번**
`os.environ` 을 채워 주면 **접속 코드는 한 줄도 손대지 않는다.**

🔴 **시크릿 이름과 필드명을 코드에 박지 않는다.** 아직 실물 확인 전이라 전부 환경변수로 받는다 —
확인 후 바뀌는 것은 **설정이지 이 파일이 아니다.**

    MP_SECRET_NAMES  mp/prod/pipeline-secrets,mp/prod/data-secrets
    MP_SECRET_KEYS   PGPASSWORD,DATA_GO_KR_SERVICE_KEY,ES_PASSWORD=ES_PIPELINE_WRITER_PASSWORD
                     └ 이름이 같으면 그대로 · 다르면 `환경변수명=시크릿필드명`

둘 중 하나라도 비어 있으면 **아무것도 하지 않는다** — 로컬 개발과 CLI 실행이 그대로 돌아간다.
"""
from __future__ import annotations

import json
import os

from .runtime import logger

log = logger(__name__)

# 🔴 모듈 수준 캐시 = **웜 스타트에서 재조회를 막는다.**
# Lambda 는 한 번 뜬 실행 환경을 재사용하므로, 핸들러 밖에서 채운 이 값은 다음 호출에도 살아 있다.
# 재조회는 호출당 지연과 요금이 되고, Secrets Manager 는 호출 과금 대상이다.
_cache: dict[str, dict] = {}


def _fetch(name: str) -> dict:
    """시크릿 하나를 JSON 으로 읽는다. 값의 형상 = **번들 1개 = JSON 오브젝트 1개.**"""
    if name in _cache:
        return _cache[name]
    import boto3                                    # noqa: PLC0415 — 로컬에선 없어도 되게 지연 임포트
    from botocore.config import Config              # noqa: PLC0415

    region = os.environ.get("AWS_REGION", "ap-northeast-2")
    # 🔴 **기본값으로 두면 실패가 5분 걸린다.** botocore 기본 connect timeout 60초 × 재시도
    #    5회 ≈ 300초이고, 그동안 Lambda 는 계속 과금되며 매달린다.
    #    2026-08-18 실측이 정확히 그랬다 — 배치 5종이 **308초**씩 물고 있다가 클라이언트가
    #    먼저 포기했고, 로그를 열기 전에는 «PG 가 안 되나 · 권한인가 · 코드인가» 가 구분되지
    #    않았다. 원인은 VPC 엔드포인트 SG 한 줄이었다.
    # 🔵 짧게 잡으면 **같은 고장이 10초 안에, `ConnectTimeoutError` 라는 이름으로** 드러난다.
    #    네트워크가 정상이면 이 호출은 수십 ms 라 짧은 값이 정상 경로를 해치지 않는다.
    cfg = Config(connect_timeout=3, read_timeout=5,
                 retries={"max_attempts": 2, "mode": "standard"})
    raw = boto3.client("secretsmanager", region_name=region,
                       config=cfg).get_secret_value(SecretId=name)
    try:
        bundle = json.loads(raw["SecretString"])
    except (KeyError, json.JSONDecodeError) as exc:
        # 🔴 값은 절대 메시지에 넣지 않는다 — 로그가 곧 유출 경로가 된다.
        raise RuntimeError(f"시크릿 {name!r} 이 JSON 오브젝트가 아니다") from exc
    _cache[name] = bundle
    log.info("시크릿 적재 · name=%s · 필드 %d개", name, len(bundle))   # 이름과 개수만, 값은 안 찍는다
    return bundle


def inject() -> list[str]:
    """설정에 적힌 키들을 `os.environ` 에 채운다. 채운 **환경변수 이름 목록**을 돌려준다.

    🔴 **이미 값이 있는 환경변수는 덮지 않는다.** 로컬 `.env` 나 함수 환경변수로 직접 준 값이
    이기게 해서, 디버깅할 때 *"어디서 온 값인지 모르겠다"* 가 생기지 않게 한다.
    """
    names = [n.strip() for n in os.environ.get("MP_SECRET_NAMES", "").split(",") if n.strip()]
    keys = [k.strip() for k in os.environ.get("MP_SECRET_KEYS", "").split(",") if k.strip()]
    if not names or not keys:
        log.debug("MP_SECRET_NAMES/KEYS 미설정 — 시크릿 주입 건너뜀(로컬·CLI 정상 경로)")
        return []

    bundles = [(n, _fetch(n)) for n in names]
    filled, missing = [], []
    for spec in keys:
        env_name, _, field = spec.partition("=")
        field = field or env_name                  # `=` 가 없으면 이름이 같다는 뜻
        if os.environ.get(env_name):
            continue                               # 이미 있으면 존중한다
        for src, bundle in bundles:
            if field in bundle:
                os.environ[env_name] = str(bundle[field])
                filled.append(env_name)
                break
        else:
            missing.append(f"{env_name}(={field})")

    if missing:
        # 🔴 죽이지 않고 알린다 — 그 값을 안 쓰는 함수도 이 어댑터를 공유하기 때문이다.
        #    실제로 필요한 값이면 접속 시점에 터지고, 그때 이 줄이 원인을 가리킨다.
        log.warning("시크릿에서 못 찾은 키 %d개 — %s", len(missing), ", ".join(missing))
    log.info("환경변수 주입 %d개 — %s", len(filled), ", ".join(filled) or "없음")
    return filled
