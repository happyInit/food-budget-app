"""통계청/국가데이터처 온라인가격(15080757) → price_item / price_online_daily (#6).

getPriceItemList → 전체 품목(ic 6자·품목명). getPriceInfo(개별 상품 sp) → 품목·일자별
집계(min/median/max/건수). baseline 용도라 개별상품·할인가·단위는 미적재.
⚠️ 원천이 단위 미정규(20kg vs 10kg 혼재) → 시세 방향성 지표.

키는 .env DATA_GO_KR_SERVICE_KEY(디코딩키). requests params가 URL 인코딩(+→%2B) 처리.
"""
import statistics
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect, service_key  # noqa: E402

BASE = "http://apis.data.go.kr/1240000/bpp_openapi"
KEY = service_key()
# 서비스 확인용: 대표 생필 품목 + 최근 조사구간(≤30일)
TARGET_NAMES = ["쌀", "달걀", "대파", "우유", "돼지고기", "사과", "양파", "두부", "배추", "닭고기"]
RANGE = ("20260616", "20260713")  # ≤30일


def _get(op, params, keyname):
    r = requests.get(f"{BASE}/{op}", params={keyname: KEY, **params}, timeout=40)
    root = ET.fromstring(r.text)
    msg = root.findtext(".//resultMsg")
    items = [{c.tag: c.text for c in row} for row in root.findall(".//item")]
    return msg, items


def fetch_items():
    out = []
    page = 1
    while True:
        _, items = _get("getPriceItemList", {"pageNo": page, "numOfRows": 200}, "serviceKey")
        if not items:
            break
        out += [(it["ic"], it["in"]) for it in items]
        if len(items) < 200:
            break
        page += 1
    return out


def daily_agg(ic):
    _, rows = _get("getPriceInfo",
                   {"itemCode": ic, "startDate": RANGE[0], "endDate": RANGE[1],
                    "pageNo": 1, "numOfRows": 1000}, "ServiceKey")
    by_date = {}
    for r in rows:
        sp, sd = r.get("sp"), r.get("sd")
        if sp is None or sd is None:
            continue
        by_date.setdefault(sd, []).append(int(sp))
    return by_date


def main():
    items = fetch_items()
    targets = [(ic, nm) for ic, nm in items if any(t in nm for t in TARGET_NAMES)]
    with connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """insert into price_item (item_cd, item_name) values (%s,%s)
               on conflict (item_cd) do update set item_name=excluded.item_name""",
            items)
        n_price = 0
        for ic, nm in targets:
            for sd, vals in daily_agg(ic).items():
                cur.execute(
                    """insert into price_online_daily
                         (item_cd, survey_date, price_min, price_med, price_max, obs_count)
                       values (%s,%s,%s,%s,%s,%s)
                       on conflict (item_cd, survey_date) do update set
                         price_min=excluded.price_min, price_med=excluded.price_med,
                         price_max=excluded.price_max, obs_count=excluded.obs_count,
                         fetched_at=now()""",
                    (ic, sd, min(vals), round(statistics.median(vals)), max(vals), len(vals)))
                n_price += 1
        conn.commit()
    print(f"price: {len(items)} items, {len(targets)} target items, {n_price} daily rows")


if __name__ == "__main__":
    main()
