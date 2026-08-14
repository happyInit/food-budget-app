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
from _delivery import finalize  # noqa: E402  — 드라이버 무의존(confluent_kafka 안 끌어온다)
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

# ── 렌더 경합 (2026-08-10 실장애 — ①②③ 를 다 넣고도 남아 있던 진짜 원인) ─────────
# 08-01 이후 하루걸러 **첫 카테고리(907 채소)만** 유실됐다. 확정된 예외:
#
#     CrawlTruncatedError: 907(채소) 1페이지가 0건   ← 실패까지 2.46초
#
# 2.46초 = goto 성공 + 고정 대기 2초. **타임아웃이 아니라 렌더를 덜 기다린 것**이다.
# 컬리는 SPA 라 상품이 클라이언트 렌더인데 종전 코드는 `wait_until="domcontentloaded"` 뒤에
# `wait_for_timeout(2000)` 한 번으로 "2초면 그려졌겠지" 하고 넘어갔다.
# 새 브라우저 컨텍스트의 **첫 내비게이션**은 캐시·쿠키가 없어 가장 느려서 그 2초를 넘길 때가
# 있다. 그래서 늘 첫 카테고리만, 그것도 간헐적으로 깨졌다(정상인 날엔 907 도 성공한다 —
# 고정 실패가 아니라 경합이다). 뒤 카테고리들은 워밍된 컨텍스트라 2초로 충분했다.
# 🔴 17:06 KST 수동 실행에서도 재현됐다 — 시간대·봇탐지 가설은 기각.
#
# 고침 = 고정 대기를 버리고 **카드 개수가 멈출 때까지** 기다린다. 두 실패를 동시에 피해야 한다:
#   - 너무 짧게 기다림 → 0건으로 읽는다 (지금 이 사고)
#   - 첫 카드만 기다림  → 96건 중 일부만 읽는다 (새로운 조용한 절단을 만든다)
# 그래서 "한 장 다 찼으면 즉시 통과, 아니면 개수가 안정될 때까지" 두 갈래로 간다.
PAGE_SIZE = 96              # 컬리 페이지당 상품 수(고정). 다 찼으면 더 기다릴 이유가 없다.
RENDER_TIMEOUT_MS = 15_000  # 여기까지 기다려도 0건이면 진짜 0건으로 본다(빈 페이지 = 정상 종료 신호)
RENDER_POLL_MS = 500
RENDER_STABLE_POLLS = 2     # 같은 개수가 연속 2회 = 그리기가 끝났다고 본다(≈1초)

# ── 첫 내비게이션에서 _app.js 가 죽는다 (2026-08-11 실장애 — 위 고침으로도 안 잡힌 것) ──
# 위 "렌더 경합" 고침(고정대기 → 개수 안정화 대기)을 배포한 뒤에도 907 이 계속 죽었고,
# **08-11 부터는 간헐이 아니라 매일** 죽었다. 프로덕션 이미지·네트워크에서 재현한 결과:
#
#     907(1st)=0 · 908(2nd)=96 · 907(3rd)=96     ← 907 은 무죄. **첫 내비게이션**이 실패한다
#
# 실패한 1st 는 HTTP 200 인데 `body` 텍스트가 **빈 문자열**이고 `img` 개수도 0 이었다.
# 상품만 없는 게 아니라 헤더·메뉴까지 통째로 없다 = **JS 가 아예 실행되지 않았다.**
# 네트워크 이벤트로 범인을 잡았다:
#
#     [FAILED] https://res.kurly.com/v/2026.08.11.h1/.../pages/_app-*.js
#              net::ERR_NETWORK_CHANGED
#
# `_app.js` 는 Next.js 앱의 **루트 번들**이라 이게 없으면 React 가 부팅을 못 한다.
# URL 의 `/v/2026.08.11.h1/` = 컬리가 08-11 에 배포한 빌드 — 우리 실패 시작일과 일치한다.
#
# 🔴 그래서 **대기를 늘리는 방향으로는 절대 안 고쳐진다.** 15초를 다 기다려도(폴링 궤적이
#    30회 내내 0) 오지 않은 스크립트는 오지 않는다. 기존 RENDER_TIMEOUT_MS 는 그대로 둔다.
#
# 고침 = `wait_until` 을 `domcontentloaded` → **`load`** 로 올린다.
# `domcontentloaded` 는 HTML 파싱만 끝나면 반환해 **번들을 받기 전에** 넘어간다.
# `load` 는 스크립트를 포함한 서브리소스까지 기다리므로 `_app.js` 도착이 보장된다.
# 실측(프로덕션 이미지, 콜드 컨텍스트 2라운드) = 907 이 첫 번째인데도 **96건 · 1.5초**.
GOTO_WAIT_UNTIL = "load"
RELOAD_ON_EMPTY_FIRST_PAGE = True  # 그래도 0 이면 한 번은 다시 받아 본다(아래 crawl_category)


class CrawlTruncatedError(RuntimeError):
    """수확이 잘린 정황 — 성공으로 마감하면 안 되는 상태."""


async def _goto_with_retry(page, url, code):
    """페이지 이동. 타임아웃만 재시도한다 — 차단은 RST 가 아니라 무응답으로 오기 때문이다."""
    for attempt in range(1, GOTO_ATTEMPTS + 1):
        try:
            await page.goto(url, wait_until=GOTO_WAIT_UNTIL, timeout=GOTO_TIMEOUT_MS)
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


async def _wait_for_cards(page):
    """상품 카드가 **다 그려질 때까지** 기다리고 그 개수를 돌려준다.

    반환 0 = `RENDER_TIMEOUT_MS` 동안 카드가 하나도 안 나타났다. 호출부는 이걸
    "빈 페이지"로 해석하는데, 1페이지에서면 그건 정상일 수 없으므로 실패로 마감된다(가드 ①).

    개수가 멈추는 것을 기준으로 삼는 이유는 위 상수 블록에 적었다 — 고정 대기는 짧으면
    0건, 첫 카드만 기다리면 부분 수확이라 둘 다 조용한 절단이 된다.
    """
    stable = 0
    previous = -1
    for _ in range(max(1, RENDER_TIMEOUT_MS // RENDER_POLL_MS)):
        count = await page.locator(kurly.ITEM_SELECTOR).count()
        if count >= PAGE_SIZE:
            return count                     # 한 장이 다 찼다 — 더 기다릴 이유가 없다
        if count > 0 and count == previous:
            stable += 1
            if stable >= RENDER_STABLE_POLLS:
                return count                 # 마지막 페이지처럼 96 미만으로 끝나는 경우
        else:
            stable = 0
        previous = count
        await page.wait_for_timeout(RENDER_POLL_MS)
    return max(previous, 0)


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
        # 🔴 종전엔 여기가 `wait_for_timeout(2000)` 이었다 — 그 2초가 2026-08-10 사고의 원인이다.
        cards = await _wait_for_cards(page)

        # 마지막 방어선 — `load` 로 _app.js 는 잡히지만, 번들이 죽는 경로가 그거 하나라고
        # 단정할 근거는 없다. 1페이지가 통째로 비면 **원인을 묻지 않고** 한 번 다시 받는다.
        # ⚠️ 1페이지에서만 한다. 뒤 페이지의 0건은 "페이지네이션 끝"이라는 정상 신호라
        #    거기서 리로드하면 매 카테고리 끝마다 헛수고를 한 번씩 하게 된다.
        if cards == 0 and page_num == 1 and RELOAD_ON_EMPTY_FIRST_PAGE:
            log.warning(
                "kurly 1페이지가 비어 리로드 재시도",
                extra={
                    "event": "application_log",
                    "component": COMPONENT,
                    "source": "kurly",
                    "operation": OP_CATEGORY_CRAWL,
                    "result": "retry",
                    "category_code": code,
                    "url": url,
                },
            )
            await page.reload(wait_until=GOTO_WAIT_UNTIL, timeout=GOTO_TIMEOUT_MS)
            await _wait_for_cards(page)

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
    """Kafka 프로듀서 싱크 (design.md §7.1: confluent-kafka 크롤러). 지연 import(파일모드 무의존).

    🔴 종전엔 `prod.flush` 를 그대로 closer 로 넘겼고, 호출부는 `close()` 의 **반환값을 버렸다**.
       즉 크롤은 다 성공해도 전달이 통째로 실패하면 그대로 `result: "success"` 였다(#558).
       이제 프로듀서를 그대로 돌려주고, 마감 판정은 run() 이 `_delivery.finalize` 로 한다.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines/stream"))
    from _kafka import producer, TOPIC_RETAIL_RAW
    prod = producer(COMPONENT)

    def sink(rec):
        prod.produce(TOPIC_RETAIL_RAW, key=f"kurly:{rec.get('product_id')}".encode(),
                     value=json.dumps(rec, ensure_ascii=False).encode(),
                     headers=[("source", b"kurly")])
        prod.poll(0)          # delivery report 수거 — 콜백이 여기서 실행된다
    return sink, prod, f"kafka:{TOPIC_RETAIL_RAW}"


async def run(kafka=False, out=None, s3=False):
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
    kafka_prod = None
    if kafka:                                   # 크롤하며 레코드별 직접 produce
        sink, kafka_prod, dest = _kafka_sink()
        sinks.append(sink); dests.append(dest)
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
                        # 타입명만 남긴다. 트레이스백은 log.exception 이 exc_info 로 넘기고
                        # 포맷터가 exception 필드로 직렬화한다.
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

    out_path = None
    if write_file:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = Path(out) if out else OUTPUT_DIR / f"kurly_products_{ts}.json"
        # 포맷은 확장자가 정한다 — 기존 .json(배열) 소비자를 깨뜨리지 않으면서 S3 경로에 JSONL 을 준다.
        # 🔴 컨슈머 계약이 JSONL 인 이유 = 객체를 통째로 파싱하지 않고 한 줄씩 흘려보내야
        #    레코드 1건이 깨져도 나머지가 산다(_refinery 의 레코드 단위 격리).
        with open(out_path, "w", encoding="utf-8") as f:
            if str(out_path).endswith(".jsonl"):
                for rec in records:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            else:
                json.dump(records, f, ensure_ascii=False, indent=2)
        dests.append(str(out_path))
    for close in closers:
        close()

    # S3 업로드 (C-44). Kafka 와 같은 원칙 — **긁은 것과 보낸 것은 다른 문제다**(#558).
    # 실패해도 이미 긁은 파일은 남기고, 성공으로 보고하지 않는다(아래 종료코드 판정에 합류).
    upload_error = None
    if s3:
        if out_path is None:  # 인자 검증(main)이 보장하는 불변식 — 깨졌으면 조용히 넘기지 않는다
            raise RuntimeError("--s3 인데 출력 파일이 없다")
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines/transport"))
        from _s3 import upload_run  # noqa: PLC0415 — 파일모드는 boto3 무의존

        try:
            key = upload_run(out_path, "retail", "kurly")
            dests.append(f"s3:{key}")
            log.info(
                "kurly crawl uploaded",
                extra={"event": "crawl_uploaded", "component": COMPONENT, "source": "kurly",
                       "stream": "retail", "object_key": key, "record_count": n,
                       "result": "success"},
            )
        except Exception as exc:  # noqa: BLE001 — 사유와 무관하게 성공으로 마감하지 않는다
            upload_error = exc
            log.exception(
                "kurly crawl upload failed",
                extra={"event": "sink_write_failed", "component": COMPONENT, "source": "kurly",
                       "stream": "retail", "operation": "s3.put_object",
                       "error_type": type(exc).__name__, "record_count": n, "retryable": True},
            )

    # 🔴 Kafka 마감 — **긁은 것과 보낸 것은 다른 문제다**(#558).
    #    종전엔 `prod.flush()` 를 반환값 없이 부르고 끝냈다. flush 가 세는 건 "아직 큐에 남았나"
    #    뿐이라, delivery.timeout.ms(5분) 만료로 영구 실패한 메시지는 **0 으로 보인다**.
    #    이관 후엔 크롤러=온프렘 / 브로커=AWS 라 터널 5분 단절이 곧 그 회차 통째 유실이다.
    delivery = finalize(kafka_prod, produced=n) if kafka_prod is not None else None

    # 🔴 여기가 2026-08-03 사고의 핵심이다 — 종전엔 무조건 success 로 마감했다.
    #    이미 produce 된 레코드는 되돌리지 않는다(부분 데이터가 무데이터보다 낫다).
    #    다만 **성공으로 보고하지는 않는다** — 종료코드 1 이면 Job 이 Failed 로 남아
    #    MpPollerStale 이 울고, lastSuccessfulTime 이 갱신되지 않는다.
    shortfall = n < MIN_TOTAL_RECORDS
    undelivered = delivery is not None and not delivery.ok
    if failed or shortfall or undelivered or upload_error is not None:
        reason = ("category_failure" if failed
                  else "record_count_below_floor" if shortfall
                  else "delivery_unconfirmed" if undelivered
                  else "upload_unconfirmed")
        log.error(
            f"kurly poller completed with loss — {delivery.summary() if delivery else ''}".strip(" —"),
            extra={
                "event": "crawler_failed",
                "component": COMPONENT,
                "source": "kurly",
                "result": "failure",
                "record_count": n,
                "failed_categories": failed,
                "min_expected": MIN_TOTAL_RECORDS,
                "reason": reason,
                **({"delivered_count": delivery.delivered,
                    "failed_count": delivery.failed,
                    "remaining_count": delivery.remaining} if delivery else {}),
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
            # 🔴 "긁은 수"가 아니라 **브로커가 ack 한 수**. 둘이 같아야 정상이다.
            **({"delivered_count": delivery.delivered} if delivery else {}),
        },
    )
    return 0


def main():
    ap = argparse.ArgumentParser(description="마켓컬리 상품 크롤러 (Playwright)")
    ap.add_argument("--kafka", action="store_true",
                    help="Kafka retail.crawl.raw로 직접 produce (파일 중간단계 없이 스트리밍)")
    ap.add_argument("--out", help="출력 경로. 확장자가 .jsonl 이면 JSONL, 아니면 JSON 배열 "
                                  "(기본 output/타임스탬프.json; --kafka 시 생략)")
    ap.add_argument("--s3", action="store_true",
                    help="크롤 끝난 뒤 --out 파일을 S3 incoming/ 으로 올린다 (C-44 · Kafka 대체 경로)")
    args = ap.parse_args()
    # 🔴 --s3 는 --out(.jsonl) 을 요구한다. 컨슈머 계약이 JSONL 이고(레코드 = 한 줄),
    #    숨은 임시경로를 쓰면 파드가 죽었을 때 어디를 봐야 하는지가 사라진다.
    if args.s3 and not (args.out or "").endswith(".jsonl"):
        ap.error("--s3 에는 --out <경로>.jsonl 이 필요합니다")
    # 🔴 종료코드를 그대로 넘긴다 — 이게 없으면 위의 return 1 이 무의미하고,
    #    CronJob 은 다시 "성공"으로 보인다(2026-08-03 사고의 마지막 고리).
    sys.exit(asyncio.run(run(kafka=args.kafka, out=args.out, s3=args.s3)))


if __name__ == "__main__":
    main()
