"""부팅 시 «파일이어야만 하는 것» 을 `/tmp` 에 놓는다. **환경변수로 안 되는 것들만 여기 온다.**

## 왜 이 모듈이 필요한가

`common/secrets.py` 는 값을 `os.environ` 에 채운다. 그걸로 대부분 해결되는데 **두 가지는 안 된다**:

    ① GCP 자격증명 — google-auth 는 `GOOGLE_APPLICATION_CREDENTIALS` 가 **가리키는 파일**을 읽는다.
       JSON 문자열을 환경변수에 넣어도 라이브러리가 그걸 안 본다.
       (EKS 는 `gcp-sa` 볼륨을 `/etc/gcp/gcp-sa.json` 으로 마운트한다 — 실측 2026-08-18.
        Lambda 엔 볼륨이 없으므로 **같은 결과를 파일로 만들어** 준다.)
    ② CRF 모델 — `python-crfsuite` 가 경로를 받아 연다. 308KB 바이너리라 환경변수에 못 넣는다.

## 왜 번들에 굽지 않고 S3 인가 (사용자 확정 2026-08-18)

모델은 `ml/ingredient-ner/.gitignore` 가 `data/*` 로 막고 있다 — **레포에 안 넣기로 한 기존 판단**이다.
번들에 구우려면 그 판단을 뒤집고 공개 레포에 바이너리를 커밋해야 하며, 재학습마다 커밋이 붙는다.
🔵 S3 는 `mp-ai-*` 권한이 이미 있어 **추가 요청이 없고**, 재학습이 커밋과 분리된다.
🔴 대가 = 콜드스타트에 다운로드가 붙는다(308KB · 수백 ms). 웜에서는 아래 캐시로 0 이다.

## 🔴 `/tmp` 에 대해

Lambda 의 `/tmp` 는 **실행 환경 수명 동안 남는다**(웜 스타트에서 재사용). 그래서:
  · 매 호출 다운로드가 아니라 **컨테이너당 1회**다 — 그게 이 캐시의 존재 이유다.
  · 자격증명 파일이 남는다 ⇒ **0600 으로 쓴다.** 실행 환경은 함수 전용이라 다른 테넌트가 없지만,
    같은 함수의 다른 코드가 읽을 수 있으므로 권한을 좁히는 편이 정직하다.
"""
from __future__ import annotations

import os
import pathlib

from .runtime import logger

log = logger(__name__)

TMP = pathlib.Path("/tmp")  # noqa: S108 — Lambda 에서 쓰기 가능한 유일한 경로다


def _write(path: pathlib.Path, data: bytes, mode: int = 0o600) -> pathlib.Path:
    """🔵 이미 있으면 안 쓴다 — 웜 스타트에서 매번 디스크를 두드릴 이유가 없다."""
    if path.exists() and path.stat().st_size == len(data):
        return path
    path.write_bytes(data)
    path.chmod(mode)
    return path


def gcp_credentials() -> str | None:
    """`GCP_SA_KEY_JSON`(시크릿에서 주입됨) → `/tmp/gcp-sa.json` + 환경변수 배선.

    돌려주는 값 = 만든 파일 경로, 없으면 None. 🔵 **없어도 죽이지 않는다** — 이 모듈을
    공유하는 함수 중 GCP 를 안 쓰는 것이 더 많다. 필요한 쪽은 호출 시점에 터지고,
    그때 아래 로그가 원인을 가리킨다.
    """
    raw = os.environ.get("GCP_SA_KEY_JSON")
    if not raw:
        log.debug("GCP_SA_KEY_JSON 없음 — GCP 자격증명 배선 건너뜀")
        return None
    # 🔴 이미 값이 있으면 존중한다(`secrets.inject()` 와 같은 규약) — 로컬에서 진짜 파일을
    #    가리켜 두고 디버깅하는 경우를 덮지 않는다.
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    p = _write(TMP / "gcp-sa.json", raw.encode())
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(p)
    # 🔴 길이만 찍는다. 값은 절대 로그에 넣지 않는다(secrets.py 와 같은 규약).
    log.info("GCP 자격증명 배선 · path=%s · %d bytes", p, len(raw))
    return str(p)


def s3_asset(env_name: str, s3_uri: str, filename: str) -> str | None:
    """`s3://버킷/키` → `/tmp/<filename>` 으로 받고 `env_name` 에 경로를 넣는다.

    🔵 `env_name` 에 이미 값이 있으면 그대로 둔다 — 번들에 구운 경우·로컬 경로를 이긴다.
    """
    if os.environ.get(env_name):
        return os.environ[env_name]
    if not s3_uri.startswith("s3://"):
        log.warning("s3 URI 가 아니다 — %s=%r", env_name, s3_uri)
        return None
    bucket, _, key = s3_uri[5:].partition("/")
    dest = TMP / filename
    if not dest.exists():
        import boto3                                  # noqa: PLC0415 — 로컬에선 없어도 되게
        from botocore.config import Config            # noqa: PLC0415

        # 🔴 `secrets.py` 와 같은 이유로 짧게 잡는다 — 못 받으면 5분 매달리는 대신
        #    몇 초 안에 이름을 가진 에러로 죽어야 한다(2026-08-18 실측 308초 → 30초).
        cfg = Config(connect_timeout=3, read_timeout=15,
                     retries={"max_attempts": 2, "mode": "standard"})
        boto3.client("s3", config=cfg).download_file(bucket, key, str(dest))
        log.info("자산 적재 · %s ← %s · %d bytes", dest, s3_uri, dest.stat().st_size)
    os.environ[env_name] = str(dest)
    return str(dest)
