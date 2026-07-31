"""공용 DB 커넥션 + data.go.kr 키 로더.

.env 에서 읽으며 비밀 값은 로깅/출력하지 않는다. PG* 는 fb-data(.8) foodbudget 기본값.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
import psycopg

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")


def connect():
    return psycopg.connect(
        host=os.environ.get("PGHOST", "192.168.0.8"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "foodbudget"),
        user=os.environ.get("PGUSER", "fbapp"),
        password=os.environ.get("PGPASSWORD", ""),
    )


def es_client():
    from elasticsearch import Elasticsearch

    # basic_auth: ECK(P2)는 인증 강제. env 없으면 생략 — 현행 VM ES(무인증) 동작 불변.
    # 재색인 Job(index_recipes_es.py)도 이 클라이언트를 쓴다.
    user = os.environ.get("ES_USER", "")
    auth = (user, os.environ.get("ES_PASSWORD", "")) if user else None
    return Elasticsearch(
        f"http://{os.environ.get('ESHOST', '192.168.0.8')}:{os.environ.get('ESPORT', '9200')}",
        basic_auth=auth,
    )


def service_key() -> str:
    k = os.environ.get("DATA_GO_KR_SERVICE_KEY")
    if not k:
        raise SystemExit("DATA_GO_KR_SERVICE_KEY 없음 — .env 확인")
    return k


def repo_path(*parts) -> Path:
    return _ROOT.joinpath(*parts)
