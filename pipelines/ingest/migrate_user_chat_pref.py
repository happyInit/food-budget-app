"""운영 tier 멱등 마이그레이션: activity.user_chat_pref 1개 생성(#211, 데이터 무손상).

개인화 랭킹이 '대화 유래 선호'를 피처(user_ing_affinity)로 쓰려면 chat-insights 가 upsert 할
대상 테이블이 필요하다. apply_schema.py 는 DROP CASCADE(데이터 삭제)라 운영 tier 재적용 불가 →
이 스크립트는 정본 schema-production.sql 의 CREATE 블록만 추출해 **없을 때만** 생성(멱등).

★ SQL 은 손으로 복사하지 않고 schema-production.sql 에서 추출 — 정본 1곳 유지(전사 오류 0).
실행: python pipelines/ingest/migrate_user_chat_pref.py   (데이터 담당이 운영 tier에 1회)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect, repo_path       # noqa: E402
from apply_schema import _statements      # noqa: E402  (동일 주석·세미콜론 분리기 재사용)

_START = "CREATE TABLE IF NOT EXISTS activity.user_chat_pref"


def _ddl() -> list[str]:
    """정본 스키마에서 user_chat_pref CREATE 블록(단일 문)을 추출."""
    sql = repo_path("docs", "prd", "schema-production.sql").read_text(encoding="utf-8")
    start = sql.index(_START)
    end = sql.index(");", start) + 2      # CREATE TABLE ( ... ); 블록 끝
    return list(_statements(sql[start:end]))


def migrate() -> str:
    """반환: 'skipped:already_exists' | 'migrated'."""
    stmts = _ddl()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select to_regclass('activity.user_chat_pref')")
        if cur.fetchone()[0] is not None:     # 이미 있으면 no-op(멱등)
            return "skipped:already_exists"
        for s in stmts:
            cur.execute(s)
        conn.commit()
    return "migrated"


def main() -> None:
    print(f"activity.user_chat_pref 마이그레이션: {migrate()}")


if __name__ == "__main__":
    main()
