"""docs/prd/schema-public-data.sql 을 foodbudget 에 적용(drop→create).

서비스 확인용 반복 실행을 위해 기존 테이블을 지우고 새로 만든다. 데이터 적재는 별도 로더가 upsert.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect, repo_path  # noqa: E402

TABLES = [  # FK 역순 drop
    "recipe_ingredient", "recipe_step", "recipe",
    "price_online_daily", "price_item",
    "shelf_life_ref", "food_nutrition",
]


def _statements(sql: str):
    lines = []
    for ln in sql.splitlines():
        i = ln.find("--")
        lines.append(ln[:i] if i >= 0 else ln)
    for s in "\n".join(lines).split(";"):
        if s.strip():
            yield s.strip()


def main():
    sql = repo_path("docs", "prd", "schema-public-data.sql").read_text(encoding="utf-8")
    stmts = list(_statements(sql))
    with connect() as conn, conn.cursor() as cur:
        for t in TABLES:
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
        for s in stmts:
            cur.execute(s)
        conn.commit()
    print(f"applied: dropped {len(TABLES)} tables, ran {len(stmts)} statements")


if __name__ == "__main__":
    main()
