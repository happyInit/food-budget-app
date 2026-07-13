"""컬리·오아시스 상품 → crawl_raw 스테이징 → retail_product/retail_price 정제.

패턴(설계 §E·§F): 크롤 원본을 crawl_raw(jsonb)에 착지 → 미처리분을 읽어 상품명 정규화 →
gazetteer item_id 해소 → retail_product(SKU) + retail_price(스냅샷) → processed_at 세팅.
멱등: crawl_raw upsert(on conflict) · retail_product upsert(source,product_id) · retail_price 스냅샷.
소스 파일: crawler/kurly/output/*.json · crawler/oasis/output/*.jsonl.
"""
import glob
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect                                    # noqa: E402
from gazetteer import load_gazetteer, make_matcher         # noqa: E402
from retail_norm import make_retail_matcher, is_non_ingredient   # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def stage(cur):
    """크롤 파일 → crawl_raw(jsonb). 반환 착지 건수."""
    n = 0
    for f in glob.glob(str(ROOT / "crawler/kurly/output/*.json")):
        for p in json.load(open(f, encoding="utf-8")):
            cur.execute(
                """insert into crawl_raw (source, kind, src_key, payload, crawled_at)
                   values ('kurly','product',%s,%s,%s)
                   on conflict (source,kind,src_key,crawled_at) do nothing""",
                (str(p.get("product_id")), Jsonb(p), p.get("crawled_at")))
            n += 1
    for f in glob.glob(str(ROOT / "crawler/oasis/output/*.jsonl")):
        for line in open(f, encoding="utf-8"):
            if not line.strip():
                continue
            p = json.loads(line)
            cur.execute(
                """insert into crawl_raw (source, kind, src_key, payload, crawled_at)
                   values ('oasis','product',%s,%s,%s)
                   on conflict (source,kind,src_key,crawled_at) do nothing""",
                (str(p.get("product_id")), Jsonb(p), p.get("crawled_at")))
            n += 1
    return n


UPSERT = """insert into retail_product
  (source, product_id, name, name_norm, item_id, weight_g, volume_ml, category,
   url, image_url, storage, origin, expiry_text, last_seen)
  values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
  on conflict (source, product_id) do update
    set name=excluded.name, name_norm=excluded.name_norm, item_id=excluded.item_id,
        last_seen=now()
  returning id"""


def refine(cur):
    """crawl_raw 미처리 상품 → 정규화·매칭 → retail_product/retail_price. processed_at 세팅."""
    match = make_retail_matcher(make_matcher(load_gazetteer(cur)))
    cur.execute("select id, source, payload from crawl_raw "
                "where kind='product' and processed_at is null")
    prices, done, hit, tot = [], [], 0, 0
    for raw_id, source, p in cur.fetchall():
        iid, canon, meth, nm = match(p.get("name", ""))
        if source == "kurly":
            cur.execute(UPSERT, ("kurly", str(p["product_id"]), p.get("name"), nm, iid,
                                 p.get("weight_grams"), p.get("volume_ml"), p.get("category_name"),
                                 p.get("detail_url"), p.get("image_url"), None, None, None))
            rpid = cur.fetchone()[0]
            price = p.get("sale_price")
            row = (rpid, p.get("crawled_at"), price, p.get("original_price"),
                   p.get("discount_rate"), "general", None, None, None)
        else:  # oasis
            cur.execute(UPSERT, ("oasis", str(p["product_id"]), p.get("name"), nm, iid,
                                 p.get("weight_g"), None, str(p.get("category_id") or ""),
                                 p.get("url"), p.get("image_url"), p.get("storage"),
                                 p.get("origin"), p.get("expiry_text")))
            rpid = cur.fetchone()[0]
            price = p.get("price")
            td = p.get("timedeal_end")                       # epoch ms → timestamptz
            td = datetime.fromtimestamp(td / 1000, tz=timezone.utc) if td else None
            row = (rpid, p.get("crawled_at"), price, None, None, p.get("deal_type"),
                   td, p.get("unit_price"), p.get("is_sold_out"))
        if price is not None and p.get("crawled_at"):
            prices.append(row)
        tot += 1
        hit += iid is not None
        done.append(raw_id)
    cur.executemany(
        """insert into retail_price
             (retail_product_id, crawled_at, price, original_price, discount_rate,
              deal_type, timedeal_end, unit_price, is_sold_out)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
           on conflict (retail_product_id, crawled_at) do nothing""", prices)
    cur.executemany("update crawl_raw set processed_at=now() where id=%s", [(i,) for i in done])
    return tot, hit, len(prices)


def coverage(cur):
    """전체 retail_product 재매칭(최신 큐레이션 반영·item_id 갱신) + 재료-스코프 커버리지.
    분모 = 매칭 + 미매칭 재료(비재료는 is_non_ingredient로 제외). 앱 목적(재료→가격비교)과 일치."""
    match = make_retail_matcher(make_matcher(load_gazetteer(cur)))
    cur.execute("select id, name from retail_product")
    upd, matched, unm_ing = [], 0, 0
    for rid, name in cur.fetchall():
        iid = match(name)[0]
        upd.append((iid, rid))
        if iid is not None:
            matched += 1
        elif not is_non_ingredient(name):
            unm_ing += 1
    cur.executemany("update retail_product set item_id=%s where id=%s", upd)
    return len(upd), matched, matched + unm_ing


def main():
    with connect() as conn, conn.cursor() as cur:
        n_stage = stage(cur)
        tot, hit, n_price = refine(cur)
        n_all, matched, denom = coverage(cur)
        conn.commit()
    print(f"소매 적재: crawl_raw 착지 {n_stage} · retail_product {tot} · retail_price {n_price}")
    pct = f"{round(100*hit/tot,1)}%" if tot else "—(신규 없음)"
    print(f"  적재분 item_id 매칭(인라인): {hit}/{tot} = {pct}")
    print(f"  전체 재료-스코프 커버리지: {matched}/{denom} = {round(100*matched/denom,1)}% "
          f"(전체 {n_all} · 비재료 {n_all-denom} 제외)")


if __name__ == "__main__":
    main()
