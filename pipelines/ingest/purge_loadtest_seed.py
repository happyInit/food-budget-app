"""부하테스트 시드 상품 정리 — `TEST-` 접두 product_id 를 소매 테이블에서 제거.

**왜 필요한가.** 부하테스트로 핫딜 엔드포인트를 때리려면 딜 데이터가 있어야 해서 합성 상품을
`retail.crawl.raw`/`retail.deal.raw` 에 발행하는 일이 있다(실제 2026-07-20, 2,600건). 시드 자체는
정당한 도구지만 **정리 절차가 없어 프로덕션에 남았고**, 핫딜 API 응답 10건 중 9건이 시드로
채워졌다(`/api/prices/hotdeals` 는 물질화 뷰를 안 거치고 원본 테이블을 직접 조회한다).
가격 비교는 오염되지 않았다 — 시드는 `item_id` 가 없어 `retail_unit_price` 에서 빠진다.

시드 발행 스크립트는 repo 에 없다(임시). 이 스크립트는 **정리 쪽만** 표준화한다 —
부하테스트가 끝나면 `--commit` 으로 한 번 돌리면 된다. 여러 번 돌려도 안전(멱등).

안전장치:
  · 기본은 **드라이런**. 실제 삭제는 `--commit` 필요.
  · 매칭된 상품에 `item_id` 가 하나라도 붙어 있으면 **중단** — 진짜 상품이 접두어를 가졌다는
    뜻이므로 사람이 봐야 한다.
  · `retail_price` 는 FK ON DELETE CASCADE 로 함께 지워진다(`schema-public-data.sql`).

사용:
  python pipelines/ingest/purge_loadtest_seed.py             # 드라이런(건수만)
  python pipelines/ingest/purge_loadtest_seed.py --commit    # 실제 삭제
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect                       # noqa: E402
from refresh_price_matview import _flush_price_cache   # noqa: E402

PREFIX = "TEST-"        # 시드 product_id / crawl_raw.src_key 접두어

COUNT_PRODUCT = "select count(*) from retail_product where product_id like %s"
COUNT_PRICE = """select count(*) from retail_price rp
                   join retail_product p on p.id = rp.retail_product_id
                  where p.product_id like %s"""
COUNT_RAW = "select count(*) from crawl_raw where src_key like %s"
# 진짜 상품이 접두어를 가졌는지 = item_id 가 붙었는지로 판별(시드는 gazetteer 매칭이 안 된다)
GUARD = "select count(*) from retail_product where product_id like %s and item_id is not null"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="실제로 삭제(미지정 시 드라이런)")
    args = ap.parse_args()
    like = PREFIX + "%"

    with connect() as conn, conn.cursor() as cur:
        cur.execute("SET lock_timeout = '15s'")
        cur.execute(COUNT_PRODUCT, (like,)); n_prod = cur.fetchone()[0]
        cur.execute(COUNT_PRICE, (like,)); n_price = cur.fetchone()[0]
        cur.execute(COUNT_RAW, (like,)); n_raw = cur.fetchone()[0]
        cur.execute(GUARD, (like,)); n_guard = cur.fetchone()[0]

        print(f"'{PREFIX}' 시드 — retail_product {n_prod:,} · retail_price {n_price:,}(CASCADE) "
              f"· crawl_raw {n_raw:,}")

        if n_guard:
            print(f"★ 중단: 매칭된 상품 {n_guard:,}건에 item_id 가 붙어 있다. 진짜 상품이 "
                  f"'{PREFIX}' 접두어를 가졌을 수 있으니 사람이 확인할 것.")
            raise SystemExit(2)

        if not (n_prod or n_raw):
            print("정리할 시드 없음.")
            return

        if not args.commit:
            print("드라이런 — 삭제하지 않음. 실제로 지우려면 --commit")
            return

        cur.execute("delete from crawl_raw where src_key like %s", (like,))
        d_raw = cur.rowcount
        cur.execute("delete from retail_product where product_id like %s", (like,))
        d_prod = cur.rowcount
        if (d_raw, d_prod) != (n_raw, n_prod):
            conn.rollback()
            print(f"★ 롤백: 삭제 건수 불일치(raw {d_raw}≠{n_raw} 또는 product {d_prod}≠{n_prod})")
            raise SystemExit(3)
        conn.commit()
        print(f"삭제 완료 — retail_product {d_prod:,} · crawl_raw {d_raw:,} "
              f"(retail_price {n_price:,} CASCADE)")

    # 핫딜 응답 캐시는 원본 테이블 기반이라 TTL(120s) 만료 전까지 시드를 계속 보여준다 → 즉시 무효화.
    print(f"Price 캐시 무효화: {_flush_price_cache()}")


if __name__ == "__main__":
    main()
