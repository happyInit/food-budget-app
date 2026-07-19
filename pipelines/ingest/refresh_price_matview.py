"""가격 물질화 뷰(retail_unit_price) 리프레시 — 크롤 후 실행.

retail_unit_price 는 일반 뷰였을 때 매 요청마다 retail_price 시계열 전체에 윈도우+정규식을
재계산해 Price·MealPlan 병목의 근원이었다(부하테스트, #186). 물질화 후에는 크롤(일1~2회)
직후 이 스크립트로 갱신한다 — 조회는 저장된 결과를 읽어 즉시.

운영 배선(데이터 담당):
- 배치 크롤(load_retail.main())은 끝에서 이 함수를 호출해 즉시 갱신한다.
- 스트리밍(consume_retail)로 상시 적재하는 경우, 폴 윈도우(11~12시·17~18시 등) 뒤에
  이 스크립트를 cron/systemd timer 로 스케줄한다. 예) `python pipelines/ingest/refresh_price_matview.py`

CONCURRENTLY: 유니크 인덱스(retail_unit_price_id_idx)가 있어야 하며, 갱신 중에도 읽기를 막지
않는다. 단 '최초 1회'는 CONCURRENTLY 불가(미populate 상태) → 일반 REFRESH 로 폴백한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect                                    # noqa: E402

_MATVIEW = "retail_unit_price"


def refresh_price_matview() -> str:
    """retail_unit_price 를 갱신. 반환 = 사용한 모드('concurrent'|'plain'|'skipped:<이유>').

    - 대상이 물질화 뷰가 아니면(아직 마이그레이션 전) 건너뛴다(배치가 실패하지 않게).
    - CONCURRENTLY 우선, 미populate/락 등으로 실패하면 일반 REFRESH 로 폴백.
    REFRESH ... CONCURRENTLY 는 트랜잭션 블록 안에서 못 도므로 autocommit 커넥션을 쓴다.
    """
    conn = connect()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            # relkind: 'm'=물질화 뷰, 'v'=일반 뷰, 없음=미존재. 물질화 뷰가 아니면 skip.
            cur.execute("select relkind from pg_class where relname = %s", (_MATVIEW,))
            row = cur.fetchone()
            if row is None:
                return "skipped:absent"
            if row[0] != "m":
                return "skipped:not_materialized"   # 마이그레이션(뷰→물질화) 선행 필요
            try:
                cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {_MATVIEW}")
                return "concurrent"
            except Exception:                        # noqa: BLE001 — 최초 1회 미populate 등 → 일반 갱신 폴백
                cur.execute(f"REFRESH MATERIALIZED VIEW {_MATVIEW}")
                return "plain"
    finally:
        conn.close()


def main() -> None:
    mode = refresh_price_matview()
    print(f"retail_unit_price 리프레시: {mode}")


if __name__ == "__main__":
    main()
