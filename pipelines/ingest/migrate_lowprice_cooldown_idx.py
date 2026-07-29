"""운영 tier 멱등 마이그레이션: notification_lowprice_cooldown_idx 1개 생성(#9, 데이터 무손상).

최저가 fan-out 컨슈머(`pipelines/stream/consume_price_anomaly.py`)는 이벤트마다
"이 유저에게 이 품목을 최근 7일 안에 보냈나"를 확인한다. 이 조건이 `payload->>'item_id'`
표현식이라 기존 인덱스로는 못 타 알림이 쌓일수록 순차 스캔이 된다.
apply_schema.py 는 DROP CASCADE(데이터 삭제)라 운영 tier 재적용 불가 →
이 스크립트는 정본 schema-production.sql 의 CREATE INDEX 블록만 추출해 **없을 때만** 생성(멱등).

★ SQL 은 손으로 복사하지 않고 schema-production.sql 에서 추출 — 정본 1곳 유지.
실행: python pipelines/ingest/migrate_lowprice_cooldown_idx.py   (데이터 담당이 운영 tier에 1회)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect, repo_path       # noqa: E402
from apply_schema import _statements      # noqa: E402  (동일 주석·세미콜론 분리기 재사용)

_START = "CREATE INDEX IF NOT EXISTS notification_lowprice_cooldown_idx"
_INDEX = "notification_lowprice_cooldown_idx"


def _ddl() -> list[str]:
    """정본 스키마에서 쿨다운 인덱스 CREATE 블록(단일 문)을 추출."""
    sql = repo_path("docs", "prd", "schema-production.sql").read_text(encoding="utf-8")
    start = sql.index(_START)
    end = sql.index(";", start) + 1
    return list(_statements(sql[start:end]))


def migrate() -> str:
    """반환: 'skipped:already_exists' | 'migrated'."""
    stmts = _ddl()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select to_regclass(%s)", (f"notify.{_INDEX}",))
        if cur.fetchone()[0] is not None:     # 이미 있으면 no-op(멱등)
            return "skipped:already_exists"
        for s in stmts:
            cur.execute(s)
        conn.commit()
    return "migrated"


if __name__ == "__main__":
    print(f"{_INDEX}: {migrate()}")
