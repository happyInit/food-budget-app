# 최소 프로토타입 — 수집한 상품을 JSON 파일 또는 Kafka(--kafka)로 저장
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from parsers import kurly

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

CATEGORIES = {
    "907": "채소",
    "908": "과일·견과·쌀",
    "909": "수산·해산·건어물",
    "910": "정육·가공육·달걀",
}

OUTPUT_DIR = Path(__file__).parent / "output"

# 페이지당 96건 고정, 카테고리별 전체 페이지 수가 달라 빈 페이지가 나올 때까지 순회한다.
MAX_PAGES = 100  # 무한루프 방지용 상한


async def crawl_category(page, code, name):
    print(f"\n=== {name} ({code}) 수집 시작 ===")
    all_products = []
    seen_ids = set()

    for page_num in range(1, MAX_PAGES + 1):
        url = f"https://www.kurly.com/categories/{code}?page={page_num}"
        await page.goto(url, wait_until="domcontentloaded", timeout=50000)
        await page.wait_for_timeout(2000)

        products = await kurly.parse_page(page)
        new_products = [p for p in products if p["product_id"] not in seen_ids]
        if not new_products:
            break

        seen_ids.update(p["product_id"] for p in new_products)
        all_products.extend(new_products)

    print(f"{name}: 상품 {len(all_products)}건")
    return all_products


def _kafka_sink():
    """Kafka 프로듀서 싱크 (design.md §7.1: confluent-kafka 크롤러). 지연 import(파일모드 무의존)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines/stream"))
    from _kafka import producer, TOPIC_RETAIL_RAW
    prod = producer()

    def sink(rec):
        prod.produce(TOPIC_RETAIL_RAW, key=f"kurly:{rec.get('product_id')}".encode(),
                     value=json.dumps(rec, ensure_ascii=False).encode(),
                     headers=[("source", b"kurly")])
        prod.poll(0)
    return sink, prod.flush, f"kafka:{TOPIC_RETAIL_RAW}"


async def run(kafka=False, out=None):
    crawled_at = datetime.now(timezone.utc).isoformat()
    sinks, closers, dests = [], [], []
    if kafka:                                   # 크롤하며 레코드별 직접 produce
        sink, flush, dest = _kafka_sink()
        sinks.append(sink); closers.append(flush); dests.append(dest)
    write_file = bool(out) or not kafka          # --out 지정 또는 (kafka 없을 때) 기본 파일
    if write_file:
        OUTPUT_DIR.mkdir(exist_ok=True)

    records, n = [], 0
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT, locale="ko-KR")
        page = await context.new_page()

        for code, name in CATEGORIES.items():
            products = await crawl_category(page, code, name)
            for product in products:
                rec = {**product, "category_code": code, "category_name": name,
                       "crawled_at": crawled_at}
                for s in sinks:
                    s(rec)                       # Kafka produce (레코드별 스트리밍)
                if write_file:
                    records.append(rec)
                n += 1

        await browser.close()

    if write_file:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = Path(out) if out else OUTPUT_DIR / f"kurly_products_{ts}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        dests.append(str(out_path))
    for close in closers:
        close()
    print(f"\n=== 완료: 총 {n}건 → {', '.join(dests)} ===")


def main():
    ap = argparse.ArgumentParser(description="마켓컬리 상품 크롤러 (Playwright)")
    ap.add_argument("--kafka", action="store_true",
                    help="Kafka retail.crawl.raw로 직접 produce (파일 중간단계 없이 스트리밍)")
    ap.add_argument("--out", help="출력 JSON 경로 (기본 output/타임스탬프.json; --kafka 시 생략)")
    args = ap.parse_args()
    asyncio.run(run(kafka=args.kafka, out=args.out))


if __name__ == "__main__":
    main()