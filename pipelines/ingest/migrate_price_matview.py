"""운영 데이터 tier 마이그레이션: retail_unit_price 일반 뷰 → 물질화 뷰(#186).

apply_schema.py 는 DROP TABLE CASCADE(데이터 삭제)라 운영 tier에 재적용할 수 없다. 이 스크립트는
데이터를 건드리지 않고 **뷰 정의만** 물질화 뷰로 전환한다(멱등 — 이미 물질화면 skip).

동작:
  1) retail_unit_price 가 이미 물질화 뷰('m')면 아무것도 안 함.
  2) 일반 뷰('v')/부재면: 의존 뷰(compare 2종)와 함께 DROP → schema-public-data.sql 의
     '정본' 정의(매트뷰 + 인덱스 + compare 2종)를 그대로 추출해 재생성.
전환 후 조회는 저장된 결과를 읽어 즉시. 이후 갱신은 refresh_price_matview.py(크롤 후).

★ SQL 은 손으로 복사하지 않고 schema-public-data.sql 에서 추출 — 정본 1곳 유지(전사 오류 0).
실행: python pipelines/ingest/migrate_price_matview.py   (데이터 담당이 운영 tier에 1회)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect, repo_path       # noqa: E402
from apply_schema import _statements      # noqa: E402  (동일 주석·세미콜론 분리기 재사용)

# schema-public-data.sql 에서 추출할 블록 경계 — 매트뷰 시작 ~ piece_compare 끝.
_START = "CREATE MATERIALIZED VIEW retail_unit_price"
_END = "GROUP BY im.canonical_name, im.category, u.piece_unit;"
# 전환 시 함께 DROP 할 의존 뷰(compare 2종은 retail_unit_price 를 참조).
_DROP = [
    "DROP VIEW IF EXISTS retail_item_piece_compare CASCADE",
    "DROP VIEW IF EXISTS retail_item_price_compare CASCADE",
    "DROP VIEW IF EXISTS retail_unit_price CASCADE",
]


def _matview_block() -> list[str]:
    """정본 스키마에서 매트뷰+인덱스+compare 2종의 CREATE 문을 순서대로 추출."""
    sql = repo_path("docs", "prd", "schema-public-data.sql").read_text(encoding="utf-8")
    start = sql.index(_START)
    end = sql.index(_END) + len(_END)
    return list(_statements(sql[start:end]))


def migrate() -> str:
    """반환: 'skipped:already_materialized' | 'migrated'."""
    stmts = _matview_block()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select relkind from pg_class where relname = 'retail_unit_price'")
        row = cur.fetchone()
        if row is not None and row[0] == "m":
            return "skipped:already_materialized"
        for d in _DROP:                 # 의존 뷰부터(없으면 no-op) — CASCADE 안전망
            cur.execute(d)
        for s in stmts:                 # 매트뷰 + 인덱스 + compare 2종 재생성(CREATE 가 즉시 populate)
            cur.execute(s)
        conn.commit()
    return "migrated"


def main() -> None:
    print(f"retail_unit_price 마이그레이션: {migrate()}")


if __name__ == "__main__":
    main()
