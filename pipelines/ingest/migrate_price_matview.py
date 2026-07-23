"""운영 데이터 tier 마이그레이션: retail_unit_price 를 정본 정의와 일치시킨다.

apply_schema.py 는 DROP TABLE CASCADE(데이터 삭제)라 운영 tier에 재적용할 수 없다. 이 스크립트는
데이터를 건드리지 않고 **뷰 정의만** 정본(schema-public-data.sql)에 맞춘다(멱등).

동작:
  1) retail_unit_price 가 물질화 뷰('m') **이고 정의가 최신**이면 아무것도 안 함.
  2) 그 외(일반 뷰 'v' / 부재 / 구버전 정의)면: 의존 뷰(compare 2종)와 함께 DROP →
     정본 정의(매트뷰 + 인덱스 + compare 2종)를 그대로 추출해 재생성.
전환 후 조회는 저장된 결과를 읽어 즉시. 이후 갱신은 refresh_price_matview.py(크롤 후).

★ 원래는 '물질화 여부'만 봤는데(#186 1회성), 그러면 **뷰 정의가 바뀌어도 영원히 skip** 된다.
  2026-07-23 콤마 파싱 장애 수정 때 이 한계가 드러나 **정의 기반 감지**로 바꿨다.
  판정은 `pg_get_viewdef` 에 `_FIX_MARKER` 가 있는지로 한다 — PG 가 정의를 정규화해 저장하므로
  원문 문자열 비교는 불가능하고, 마커 방식이면 이후 정의 변경 때도 마커만 갱신하면 된다.

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
# 전환 시 함께 DROP 할 의존 뷰(compare 2종은 retail_unit_price 를 참조). 둘 다 일반 뷰.
_DROP_DEPS = [
    "DROP VIEW IF EXISTS retail_item_piece_compare CASCADE",
    "DROP VIEW IF EXISTS retail_item_price_compare CASCADE",
]
# retail_unit_price 자신은 **현재 relkind 에 맞는 DROP 문**을 써야 한다.
#   ⚠️ `IF EXISTS` 는 '부재'만 봐주고 **타입 불일치는 그대로 에러**다 —
#      이미 매트뷰인데 `DROP VIEW` 를 쓰면 WrongObjectType 으로 죽는다.
#      ("is not a view / HINT: Use DROP MATERIALIZED VIEW", 2026-07-23 운영 실패로 확인)
#   최초 v→m 전환기엔 'v' 였어서 DROP VIEW 하나로 충분했지만, 이제 정의 갱신 경로
#   ('m' → 새 'm')가 주 사용처라 분기해야 한다.
_DROP_SELF = {
    "m": "DROP MATERIALIZED VIEW IF EXISTS retail_unit_price CASCADE",
    "v": "DROP VIEW IF EXISTS retail_unit_price CASCADE",
}
# 배포된 정의가 최신인지 판정하는 마커 — 현 정본에만 있는 토큰.
#   ⚠️ 정본 정의를 또 바꿀 때 이 마커도 '새 정의에만 있는 토큰'으로 함께 갱신할 것.
#      안 그러면 skip 되어 변경이 운영에 영원히 반영되지 않는다.
_FIX_MARKER = "NULLIF"      # 2026-07-23 0-나눗셈 가드. 구 정의엔 없음(실측 확인).


def _matview_block() -> list[str]:
    """정본 스키마에서 매트뷰+인덱스+compare 2종의 CREATE 문을 순서대로 추출."""
    sql = repo_path("docs", "prd", "schema-public-data.sql").read_text(encoding="utf-8")
    start = sql.index(_START)
    end = sql.index(_END) + len(_END)
    return list(_statements(sql[start:end]))


def migrate() -> str:
    """반환: 'skipped:up_to_date' | 'migrated'."""
    stmts = _matview_block()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select c.relkind, "
            "       case when c.relkind in ('m','v') then pg_get_viewdef(c.oid, true) end "
            "  from pg_class c where c.relname = 'retail_unit_price'"
        )
        row = cur.fetchone()
        kind = row[0] if row is not None else None       # 'm' | 'v' | None(부재)
        if kind == "m" and _FIX_MARKER in (row[1] or ""):
            return "skipped:up_to_date"
        for d in _DROP_DEPS:            # 의존 뷰부터(없으면 no-op) — CASCADE 안전망
            cur.execute(d)
        if kind in _DROP_SELF:          # 부재면 DROP 자체가 불필요
            cur.execute(_DROP_SELF[kind])
        for s in stmts:                 # 매트뷰 + 인덱스 + compare 2종 재생성(CREATE 가 즉시 populate)
            cur.execute(s)
        conn.commit()
    return "migrated"


def main() -> None:
    print(f"retail_unit_price 마이그레이션: {migrate()}")


if __name__ == "__main__":
    main()
