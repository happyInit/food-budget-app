# 최소 프로토타입 — 수집한 상품을 JSON 파일로 저장
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


async def run():
    crawled_at = datetime.now(timezone.utc).isoformat()
    OUTPUT_DIR.mkdir(exist_ok=True)

    all_results = []

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT, locale="ko-KR")
        page = await context.new_page()

        for code, name in CATEGORIES.items():
            products = await crawl_category(page, code, name)
            for product in products:
                all_results.append({
                    **product,
                    "category_code": code,
                    "category_name": name,
                    "crawled_at": crawled_at,
                })

        await browser.close()

    # 파일명에 수집 시각을 넣어 실행할 때마다 새 파일로 쌓이게 함
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = OUTPUT_DIR / f"kurly_products_{timestamp}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n=== 완료: 총 {len(all_results)}건 저장 → {output_path} ===")


if __name__ == "__main__":
    asyncio.run(run())