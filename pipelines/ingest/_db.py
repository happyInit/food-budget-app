"""공용 DB 커넥션 + data.go.kr 키 로더.

.env 에서 읽으며 비밀 값은 로깅/출력하지 않는다.
PG*/ES* 기본값(localhost)은 로컬 개발용 placeholder 다 — 운영값은 mp-pipeline-env 가 주입한다.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
import psycopg

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")


def connect():
    return psycopg.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "foodbudget"),
        user=os.environ.get("PGUSER", "fbapp"),
        password=os.environ.get("PGPASSWORD", ""),
        # prepare_threshold=None: 서버측 prepared statement 비활성.
        # PgBouncer transaction 풀링은 **트랜잭션마다 백엔드가 바뀔 수 있어**, 켜 두면
        # `prepared statement "..." does not exist` 가 난다.
        # 🔴 앱 서비스 9종은 이미 이 설정을 갖고 있는데(`services/*/app/db.py`) **여기만 빠져 있었다.**
        #    온프렘 파이프라인은 `pg-rw` 직결이라 드러나지 않았지만, AWS 이관 후에는 **Pooler 경유**가
        #    정본이라(C-15 · eks 오버레이의 «Pooler 우회» 는 결함으로 잡혀 복구됨) 그대로 두면
        #    배치 5종이 전부 여기서 깨진다. 실패가 **첫 재사용 커넥션에서만** 나므로 산발적으로 보인다.
        prepare_threshold=None,
    )


def es_client():
    from elasticsearch import Elasticsearch

    # basic_auth: ECK(P2)는 인증 강제. env 없으면 생략 — 현행 VM ES(무인증) 동작 불변.
    # 재색인 Job(index_recipes_es.py)도 이 클라이언트를 쓴다.
    user = os.environ.get("ES_USER", "")
    auth = (user, os.environ.get("ES_PASSWORD", "")) if user else None
    return Elasticsearch(
        f"http://{os.environ.get('ESHOST', 'localhost')}:{os.environ.get('ESPORT', '9200')}",
        basic_auth=auth,
    )


def service_key() -> str:
    k = os.environ.get("DATA_GO_KR_SERVICE_KEY")
    if not k:
        raise SystemExit("DATA_GO_KR_SERVICE_KEY 없음 — .env 확인")
    return k


def repo_path(*parts) -> Path:
    return _ROOT.joinpath(*parts)
