# 최소 프로토타입 — 수집한 상품을 JSON 파일 또는 Kafka(--kafka)로 저장
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright_stealth import Stealth
from parsers import kurly

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines/stream"))
from _observability import get_pipeline_logger  # noqa: E402

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
COMPONENT = "poller-kurly"
OP_CATEGORY_CRAWL = "category.crawl"  # 로그 스키마 operation — 관측 파이프라인(Loki)이 이 문자열로 필터한다
log = get_pipeline_logger(COMPONENT)

# ── 조용한 절단 방지 (2026-08-03 실장애) ───────────────────────────────────────────
# 그날 이 크롤러는 3,324건이 아니라 **96건**만 긁고 `result: "success"` 로 마감했다.
# 원인은 네트워크(파드 DNS 서치도메인 변조 → 컬리 JS 호스트가 가짜 IP 로 풀려 차단)였고
# 고침은 config#139(dnsConfig ndots:1) 지만, **그걸 성공으로 보고한 건 이 코드다.**
# 아래 두 가드는 "네트워크가 또 이상해져도 최소한 조용히는 지나가지 않게" 하는 몫이다.
#
# ① 1페이지 0건 = 실패. 종전엔 `not new_products` 를 곧장 "페이지네이션 끝"으로 해석해
#    break 했다. 그런데 렌더 실패도 정확히 같은 모습(0건)이라 구분이 안 됐다.
#    1페이지가 비는 건 어떤 경우에도 정상이 아니다 — 여기서만은 단정할 수 있다.
# ② 총합 하한. ①은 "96건 뽑고 2페이지가 0" 인 카테고리를 못 잡는다(그날 907 이 그랬다).
#    잡 전체 수확이 하한보다 낮으면 실패로 마감한다.
#    실측 = 3,324(08-02) · 3,346(08-04 고침 검증). 하한 500 은 정상의 1/6, 절단(96)의 5배.
#    🔴 컬리가 실제로 취급 품목을 줄이면 이 잡은 매일 실패한다 — 그때는 이 상수를 고친다.
#       "조용히 잘못된 데이터"보다 "시끄럽게 멈춘 데이터"가 낫다는 판단이다.
MIN_TOTAL_RECORDS = 500

# ③ 페이지 이동 재시도. 종전엔 goto 한 번 실패 = 프로세스 전사였다(그날 그렇게 죽었다).
#    차단당하면 RST 가 아니라 무응답이라 증상이 늘 타임아웃이므로, 그 예외만 재시도한다.
GOTO_TIMEOUT_MS = 50_000
GOTO_ATTEMPTS = 3


class CrawlTruncatedError(RuntimeError):
    """수확이 잘린 정황 — 성공으로 마감하면 안 되는 상태."""


async def _goto_with_retry(page, url, code):
    """페이지 이동. 타임아웃만 재시도한다 — 차단은 RST 가 아니라 무응답으로 오기 때문이다."""
    for attempt in range(1, GOTO_ATTEMPTS + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
            return
        except PlaywrightTimeoutError:
            if attempt == GOTO_ATTEMPTS:
                raise
            log.warning(
                "kurly page goto timeout — 재시도",
                extra={
                    "event": "application_log",
                    "component": COMPONENT,
                    "source": "kurly",
                    "operation": "page.goto",
                    "result": "retry",
                    "category_code": code,
                    "url": url,
                    "attempt": attempt,
                },
            )
            await page.wait_for_timeout(2000 * attempt)


async def crawl_category(page, code, name):
    log.info(
        "kurly category crawl started",
        extra={
            "event": "application_log",
            "component": COMPONENT,
            "source": "kurly",
            "operation": OP_CATEGORY_CRAWL,
            "result": "started",
        },
    )
    all_products = []
    seen_ids = set()

    for page_num in range(1, MAX_PAGES + 1):
        url = f"https://www.kurly.com/categories/{code}?page={page_num}"
        await _goto_with_retry(page, url, code)
        await page.wait_for_timeout(2000)

        products = await kurly.parse_page(page)
        new_products = [p for p in products if p["product_id"] not in seen_ids]
        if not new_products:
            # 🔴 1페이지가 0건이면 "끝"이 아니라 "못 읽었다"다. 렌더 실패와 정상 종료가
            #    똑같이 0건으로 보이는데, **1페이지에 한해서는** 정상일 수 없다.
            if page_num == 1:
                raise CrawlTruncatedError(
                    f"{code}({name}) 1페이지가 0건 — 페이지네이션 끝이 아니라 렌더/차단 실패로 본다"
                )
            break

        seen_ids.update(p["product_id"] for p in new_products)
        all_products.extend(new_products)

    log.info(
        "kurly category crawl completed",
        extra={
            "event": "application_log",
            "component": COMPONENT,
            "source": "kurly",
            "operation": OP_CATEGORY_CRAWL,
            "result": "success",
            "category_code": code,
            "record_count": len(all_products),
        },
    )
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
    log.info(
        "kurly poller started",
        extra={
            "event": "poller_started",
            "component": COMPONENT,
            "source": "kurly",
        },
    )
    crawled_at = datetime.now(timezone.utc).isoformat()
    sinks, closers, dests = [], [], []
    if kafka:                                   # 크롤하며 레코드별 직접 produce
        sink, flush, dest = _kafka_sink()
        sinks.append(sink); closers.append(flush); dests.append(dest)
    write_file = bool(out) or not kafka          # --out 지정 또는 (kafka 없을 때) 기본 파일
    if write_file:
        OUTPUT_DIR.mkdir(exist_ok=True)

    records, n, failed = [], 0, []
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT, locale="ko-KR")
        page = await context.new_page()

        for code, name in CATEGORIES.items():
            # 🔴 카테고리별로 격리한다 — 종전엔 첫 카테고리가 죽으면 나머지 3개가 통째로
            #    날아갔다(2026-08-03: 907 타임아웃 → 그날 수확 0건). 하나가 실패해도
            #    나머지는 걷고, 실패 사실은 아래에서 종료코드로 드러낸다.
            try:
                products = await crawl_category(page, code, name)
            except Exception as exc:             # noqa: BLE001 — 어떤 실패든 나머지는 계속한다
                failed.append(code)
                log.exception(
                    "kurly category crawl failed",
                    extra={
                        "event": "application_log",
                        "component": COMPONENT,
                        "source": "kurly",
                        "operation": OP_CATEGORY_CRAWL,
                        "result": "failure",
                        "category_code": code,
                        # repr(exc) 는 임의 내용이 실릴 수 있어 JsonFormatter 허용목록에서
                        # 의도적으로 빠져 있다 — 넘겨도 로그에 안 나오는 죽은 필드였다.
                        # 타입명만 남긴다(recipebook 의 ES 장애 로그와 같은 형태). 트레이스백은
                        # log.exception 이 exc_info 로 남기고 포맷터가 exception 필드로 직렬화한다.
                        "error_type": type(exc).__name__,
                    },
                )
                continue
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

    # 🔴 여기가 이번 사고의 핵심이다 — 종전엔 무조건 success 로 마감했다.
    #    이미 produce 된 레코드는 되돌리지 않는다(부분 데이터가 무데이터보다 낫다).
    #    다만 **성공으로 보고하지는 않는다** — 종료코드 1 이면 Job 이 Failed 로 남아
    #    MpPollerStale 이 울고, lastSuccessfulTime 이 갱신되지 않는다.
    shortfall = n < MIN_TOTAL_RECORDS
    if failed or shortfall:
        log.error(
            "kurly poller completed with loss",
            extra={
                "event": "crawler_failed",
                "component": COMPONENT,
                "source": "kurly",
                "result": "failure",
                "record_count": n,
                "failed_categories": failed,
                "min_expected": MIN_TOTAL_RECORDS,
                "reason": "category_failure" if failed else "record_count_below_floor",
            },
        )
        return 1

    log.info(
        "kurly poller completed",
        extra={
            "event": "crawler_succeeded",
            "component": COMPONENT,
            "source": "kurly",
            "result": "success",
            "record_count": n,
        },
    )
    return 0


def main():
    ap = argparse.ArgumentParser(description="마켓컬리 상품 크롤러 (Playwright)")
    ap.add_argument("--kafka", action="store_true",
                    help="Kafka retail.crawl.raw로 직접 produce (파일 중간단계 없이 스트리밍)")
    ap.add_argument("--out", help="출력 JSON 경로 (기본 output/타임스탬프.json; --kafka 시 생략)")
    args = ap.parse_args()
    # 🔴 종료코드를 그대로 넘긴다 — 이게 없으면 위의 return 1 이 무의미하고,
    #    CronJob 은 다시 "성공"으로 보인다(2026-08-03 사고의 마지막 고리).
    sys.exit(asyncio.run(run(kafka=args.kafka, out=args.out)))


if __name__ == "__main__":
    main()
