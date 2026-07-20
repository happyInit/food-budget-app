"""실 PG 추출 — activity 클릭스트림 스냅샷 1회 읽기 → 피처행(오프라인 학습용).

NER과 동일 정책: PG는 읽기 1회, 학습은 오프라인. 접속은 레포 루트/.env(python-dotenv).
⚠️ activity 스키마가 라이브 DB에 **미마이그레이션**이면 테이블 부재 → 명확히 안내하고 중단
(데이터 트랙 #131·데이터담당 대기). 스키마 적용 후엔 그대로 학습으로 직행.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone

from features import EXTRACT_SQL, raw_to_feature_rows


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        for p in (".env", "../../.env", "services/chat/.env"):
            if os.path.exists(p):
                load_dotenv(p, override=False)
    except ImportError:
        pass


def connect():
    import psycopg
    ci = (f"host={os.environ.get('PGHOST', '192.168.0.8')} port={os.environ.get('PGPORT', '5432')} "
          f"dbname={os.environ.get('PGDATABASE', 'foodbudget')} user={os.environ.get('PGUSER', 'fbapp')} "
          f"password={os.environ.get('PGPASSWORD', '')}")
    return psycopg.connect(ci, connect_timeout=5)


def activity_ready(conn) -> bool:
    """activity.user_event·recipe_impression 테이블 존재 여부(미마이그레이션 조기 감지)."""
    with conn.cursor() as cur:
        cur.execute("""select count(*) from information_schema.tables
                       where table_schema='activity'
                         and table_name in ('user_event','recipe_impression','recipe_popularity','user_chat_pref')""")
        return cur.fetchone()[0] == 4


def extract_feature_rows(conn, since: datetime) -> list[dict]:
    """EXTRACT_SQL 실행 → raw dict → 피처행. 컬럼명은 커서 description으로 매핑."""
    with conn.cursor() as cur:
        cur.execute(EXTRACT_SQL, {"since": since})
        cols = [d.name for d in cur.description]
        raw = [dict(zip(cols, row)) for row in cur.fetchall()]
    return raw_to_feature_rows(raw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90, help="최근 N일 스냅샷")
    args = ap.parse_args()
    _load_env()
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    try:
        with connect() as conn:
            if not activity_ready(conn):
                print("⚠️ activity 스키마 미마이그레이션 — user_event/recipe_impression 부재.")
                print("   → schema-production.sql의 activity 테이블 적용 필요(데이터/인프라, #131 트랙).")
                print("   코드는 준비됨: 스키마 적용·데이터 축적 후 재실행하면 학습행이 나옵니다.")
                return 2
            rows = extract_feature_rows(conn, since)
    except Exception as exc:  # noqa: BLE001
        print(f"추출 실패: {type(exc).__name__}: {str(exc)[:120]}")
        return 1
    print(f"피처행 {len(rows)}건 추출(since={since:%Y-%m-%d}). → train.py 로 학습.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
