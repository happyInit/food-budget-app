"""
오아시스마켓 식자재 크롤러 (food-budget-app · 교육용·비상업)
==========================================================
설계 정본: docs/design.md §3(데이터소스)·§6.3(표준 품목 마스터)
정찰 노트: docs/design/oasis-crawl-notes.md

수집 구조 (2단계)
  1) discovery  : GET /api/product/list?categoryId=X   → 내부 JSON API. productId 목록만(가격 없음).
  2) record     : GET /product/detail/{id}             → 서버렌더 HTML. 가격 + 상품정보고시 파싱.
  출력          : JSONL(줄당 상품 1개) — design 확정 포맷.

크롤 정책 (하드)
  - 교육용·비상업·비공개 전제. anti-bot 우회 없음(오아시스는 anti-bot 부재).
  - rate-limit: 요청 간 최소 MIN_INTERVAL초. honest User-Agent(연락처 포함).
  - 가격·상품 메타만. 개인정보·리뷰 수집 안 함.

가격 정책 (팀 확정)
  - price = 판매가(화면 표시가, 실결제가)만. 정상가/할인율/쿠폰가 미수집.
  - unit_price = 상품정보 '용량'(100g당 N원, 판매가 기준) → 팩 크기 무관 가성비 비교 키.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

BASE = "https://www.oasis.co.kr"
KST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (food-budget-app educational-noncommercial crawler; contact kbs48631@gmail.com)"
MIN_INTERVAL = 1.5   # 초. 요청 사이 최소 간격(서버 부담 방지)
TIMEOUT = 20


# ---------------------------------------------------------------------------
# 레코드 스키마 (docs/design/oasis-crawl-notes.md 필드 정본과 1:1)
# ---------------------------------------------------------------------------
@dataclass
class OasisProduct:
    source: str = "oasis"
    product_id: str | None = None        # og:url 복합형 "{cat}-{prod}"
    url: str | None = None
    name: str | None = None              # og:title
    image_url: str | None = None         # og:image
    category_id: int | None = None       # discovery 컨텍스트에서 주입
    deal_type: str = "general"           # general | closeSale | timeSale
    crawled_at: str | None = None        # ISO8601 KST

    # 가격 — 판매가만
    price: int | None = None             # 판매가(실결제가) ★
    timedeal_end: int | None = None      # 핫딜 마감 epoch ms. closeSale=페이지 글로벌 타이머;
                                         # timeSale=페이지 타이머 없어 '다음 15시 리셋'으로 폴백(discover_deal, design §3.4)

    # 용량·단가 (매칭/비교 핵심)
    volume_text: str | None = None       # 고시 '용량/수량/크기' 원문
    weight_g: int | None = None          # 파싱 환산(불가 시 None)
    unit_price: int | None = None        # 상품정보 '용량' 100g당 N원
    unit_basis: str | None = None        # "100g" 등

    # 신선도·품질 (XGBoost 피처)
    storage: str | None = None           # 상품정보 '보관방법' (신선/냉장/냉동/실온)
    expiry_text: str | None = None       # 고시 '소비기한'
    origin: str | None = None            # 고시 '원산지'
    is_fresh_seasonal: bool = False      # '햇상품' 뱃지

    # 배송·재고
    delivery_types: list[str] = field(default_factory=list)
    is_sold_out: bool = False


# ---------------------------------------------------------------------------
# HTTP — rate-limit + 백오프
# ---------------------------------------------------------------------------
class Fetcher:
    def __init__(self, min_interval: float = MIN_INTERVAL):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
        self.min_interval = min_interval
        self._last = 0.0

    def _throttle(self):
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str, *, as_json: bool = False, retries: int = 3, **kw):
        for attempt in range(1, retries + 1):
            self._throttle()
            try:
                r = self.s.get(url, timeout=TIMEOUT, **kw)
                self._last = time.monotonic()
                if r.status_code == 200:
                    return r.json() if as_json else r.text
                # 4xx는 재시도 무의미
                if 400 <= r.status_code < 500:
                    print(f"  ! {r.status_code} {url}", file=sys.stderr)
                    return None
            except requests.RequestException as e:
                print(f"  ! try{attempt} {e} {url}", file=sys.stderr)
            time.sleep(self.min_interval * attempt)   # 선형 백오프
        return None


# ---------------------------------------------------------------------------
# 파싱 헬퍼
# ---------------------------------------------------------------------------
_WON = re.compile(r"([\d,]+)\s*원")
_UNIT_PRICE = re.compile(r"(\d+)\s*(g|kg|ml|l|개|구|매|포|팩)\s*당\s*([\d,]+)\s*원", re.I)
_WEIGHT = re.compile(r"([\d.]+)\s*(kg|g|ml|l)\b", re.I)


def _won_to_int(text: str | None) -> int | None:
    """'2,200원' → 2200"""
    if not text:
        return None
    m = _WON.search(text)
    return int(m.group(1).replace(",", "")) if m else None


def _parse_weight_g(text: str | None) -> int | None:
    """'800g 내외' → 800,  '1.2kg' → 1200,  '10구' → None(무게 아님)"""
    if not text:
        return None
    m = _WEIGHT.search(text)
    if not m:
        return None
    val, unit = float(m.group(1)), m.group(2).lower()
    if unit in ("kg", "l"):
        return int(val * 1000)
    if unit in ("g", "ml"):
        return int(val)
    return None


def _info_box(soup: BeautifulSoup) -> dict[str, str]:
    """상품정보 박스: <li><strong>라벨</strong> 값</li> → {라벨: 값}"""
    out: dict[str, str] = {}
    for strong in soup.select("li > strong"):
        label = strong.get_text(strip=True)
        li = strong.find_parent("li")
        # strong(라벨) 텍스트를 걷어낸 나머지 = 값
        value = li.get_text(" ", strip=True).replace(label, "", 1).strip()
        if label and value:
            out[label] = value
    return out


_GOSI_KEYS = ("소비기한", "원산지", "보관", "용량", "중량", "상품구성", "소재지", "생산자")


def _gosi_table(soup: BeautifulSoup) -> dict[str, str]:
    """상품정보제공고시 테이블 → {정규화라벨: 값}.

    상품군마다 라벨셋이 다름(채소=용량/수량/크기·원산지, 버섯=상품구성·소재지, 육류=중량 …).
    → (1) 공백 제거 정규화로 매칭, (2) 셀을 (라벨,값) 페어와이즈로 파싱(한 행에 여러 쌍 대응),
       (3) 매칭 테이블 전부 병합(중복은 첫 값 유지).
    """
    out: dict[str, str] = {}
    for table in soup.find_all("table"):
        norm = table.get_text("", strip=True).replace(" ", "")
        if not any(k in norm for k in _GOSI_KEYS):
            continue
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            for i in range(0, len(cells) - 1, 2):        # (0,1)(2,3)… 라벨:값
                key = cells[i].replace(" ", "")
                out.setdefault(key, cells[i + 1])
    return out


def _gosi_get(gosi: dict[str, str], *keys: str) -> str | None:
    """라벨 변형 순서대로 조회. '해당없음'류는 빈값 취급."""
    for k in keys:
        v = gosi.get(k)
        if v and v.replace(" ", "") not in ("해당없음", ""):
            return v
    return None


def _price_won(soup: BeautifulSoup) -> int | None:
    """판매가 = div.price 메인 컨테이너 안 <b>. (info_price 배너 함정 회피)"""
    block = soup.select_one("div.price")
    if not block:
        return None
    b = block.select_one(".textPrice b") or block.select_one("b")
    return _won_to_int(b.get_text() + "원") if b else None


def _timedeal_end(soup: BeautifulSoup) -> int | None:
    el = soup.select_one("div.price [data-end-time]")
    if el and el.get("data-end-time", "").isdigit():
        return int(el["data-end-time"])
    return None


def _meta(soup: BeautifulSoup, prop: str) -> str | None:
    m = soup.find("meta", property=prop)
    return m.get("content") if m else None


# ---------------------------------------------------------------------------
# 상세페이지 → 레코드
# ---------------------------------------------------------------------------
def parse_detail(html: str, category_id: int | None, deal_type: str = "general") -> OasisProduct:
    soup = BeautifulSoup(html, "lxml")
    p = OasisProduct(category_id=category_id, deal_type=deal_type,
                     crawled_at=datetime.now(KST).isoformat(timespec="seconds"))

    # 식별·메타
    p.name = _meta(soup, "og:title")
    p.image_url = _meta(soup, "og:image")
    p.url = _meta(soup, "og:url")
    if p.url:
        p.product_id = p.url.rstrip("/").split("/product/detail/")[-1]
    badges = [b.get_text(strip=True) for b in soup.select("span.badge_label")]
    # '햇상품'만 제철·햇상품 신호. '신상품' 등 다른 뱃지는 제외(오탐 방지). 상품명 기반 best-effort.
    p.is_fresh_seasonal = ("햇상품" in (p.name or "")) or any("햇상품" in b for b in badges)

    # 가격 — 판매가만
    p.price = _price_won(soup)
    p.timedeal_end = _timedeal_end(soup)

    # 상품정보 박스
    info = _info_box(soup)
    # 용량: "100g당 275원" → unit_price + unit_basis
    if "용량" in info:
        m = _UNIT_PRICE.search(info["용량"])
        if m:
            p.unit_price = int(m.group(3).replace(",", ""))
            p.unit_basis = f"{m.group(1)}{m.group(2).lower()}"
    p.storage = info.get("보관방법")
    if "배송구분" in info:
        p.delivery_types = re.findall(r"[가-힣]+배송", info["배송구분"])

    # 상품정보제공고시 테이블 (라벨셋이 상품군마다 달라 변형 순서로 조회)
    gosi = _gosi_table(soup)
    p.origin = _gosi_get(gosi, "원산지")
    if not p.origin:  # 별도 원산지 행이 없으면 '생산자(수입자)및소재지' 값에서 추출
        src = _gosi_get(gosi, "생산자(수입자)및소재지", "생산자및소재지", "원산지/제조국")
        if src:
            m = re.search(r"(국내산|국산|수입산|[가-힣]{2,}산)", src)
            p.origin = m.group(1) if m else src
    p.volume_text = _gosi_get(gosi, "용량/수량/크기", "중량", "상품구성", "용량")
    p.weight_g = _parse_weight_g(p.volume_text)
    p.expiry_text = _gosi_get(gosi, "소비기한", "소비기한(유통기한)", "유통기한",
                              "제조년월일/품질유지기한")
    if not p.storage:  # 상품정보 박스에 없으면 고시 '보관/취급방법'으로 폴백
        p.storage = _gosi_get(gosi, "보관방법", "보관/취급방법")

    # 품절 신호 (best-effort)
    p.is_sold_out = bool(soup.find(string=re.compile(r"일시품절|품절")) and
                         soup.select_one(".soldout, .sold_out, button[disabled]"))
    return p


# ---------------------------------------------------------------------------
# discovery
#   카테고리: 내부 JSON list API (?categoryId=X) → productId 목록.
#   딜(마감/타임세일): /product/{deal} 서버렌더 HTML의 detail 링크 파싱.
#     ⚠ ?closeSaleYn=Y / ?timeSaleYn=Y JSON 필터는 항상 []만 반환(미작동) — 딜은 HTML 서버렌더.
#     마감시각(closeSale): 개별 상품이 아니라 리스트 페이지 글로벌 타이머(closeSaleOpenYn?자정:17시).
#     timeSale: 이 글로벌 타이머 변수가 페이지에 없음 → '다음 15시 리셋'으로 폴백(design §3.4).
#       ⚠ TODO: 라이브 timeSale 페이지 타이머 구조 확인 시 실제값으로 대체(현재 15시 리셋 추정).
# ---------------------------------------------------------------------------
def discover_ids(fetcher: Fetcher, query: str, limit: int | None = None) -> list[int]:
    url = f"{BASE}/api/product/list?{query}&page=1&sort=priority&direction=desc&rows=200"
    data = fetcher.get(url, as_json=True)
    if not isinstance(data, list):
        return []
    ids = [it["productId"] for it in data if it.get("productId")]
    return ids[:limit] if limit else ids


_DEAL_PATH = {"closeSale": "/product/closeSale", "timeSale": "/product/timeSale"}
_DETAIL_ID = re.compile(r"/product/detail/([\w-]+)")
_TARGET_DATE = re.compile(r'targetDate\s*=\s*closeSaleOpenYn\s*==\s*"Y"\s*\?\s*"(\d{14})"\s*:\s*"(\d{14})"')
_OPEN_YN = re.compile(r'closeSaleOpenYn\s*=\s*"(\w)"')
TIMESALE_RESET_HOUR = 15   # 오아시스 타임세일 일일 리셋(design §3.4) — 페이지 타이머 없어 폴백 기준


def _next_reset_kst(hour: int) -> int:
    """다음 리셋(KST hour:00:00)의 epoch ms — now보다 엄격히 이후. 오늘 리셋 지났으면 내일."""
    now = datetime.now(KST)
    reset = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if now >= reset:
        reset += timedelta(days=1)
    return int(reset.timestamp() * 1000)


def discover_deal(fetcher: Fetcher, deal: str, limit: int | None = None):
    """딜 discovery — /product/{deal} 서버렌더 HTML의 detail 링크. 반환 (ids, deal_end_ms).
    deal_end_ms = 페이지 글로벌 마감(개별 상품 타이머 없음). JSON 필터 API는 미작동.
    ⚠ _TARGET_DATE/_OPEN_YN 은 closeSale 페이지 전용 → timeSale 페이지엔 타이머 변수 없음.
       timeSale은 15시 리셋(design §3.4) 기반 '다음 15:00 KST'로 폴백(임의 +6h보다 결정적).
       TODO: 라이브 timeSale 페이지 실제 타이머 구조 확인 시 그 값으로 대체."""
    html = fetcher.get(f"{BASE}{_DEAL_PATH[deal]}")
    if not html:
        return [], None
    ids = list(dict.fromkeys(_DETAIL_ID.findall(html)))
    end_ms, m, o = None, _TARGET_DATE.search(html), _OPEN_YN.search(html)
    if m and o:
        td = m.group(1) if o.group(1) == "Y" else m.group(2)      # 오픈=자정 / 미오픈=17시
        end_ms = int(datetime.strptime(td, "%Y%m%d%H%M%S").replace(tzinfo=KST).timestamp() * 1000)
    elif deal == "timeSale":
        end_ms = _next_reset_kst(TIMESALE_RESET_HOUR)             # 페이지 타이머 없음 → 리셋 기반 폴백
    return (ids[:limit] if limit else ids), end_ms


# ---------------------------------------------------------------------------
# 상세 페치 → 레코드 제너레이터 (카테고리·딜 공용)
# ---------------------------------------------------------------------------
def _fetch_details(fetcher, ids, *, category_id=None, deal_type="general", deal_end_ms=None):
    for pid in ids:
        html = fetcher.get(f"{BASE}/product/detail/{pid}")
        if not html:
            continue
        rec = parse_detail(html, category_id=category_id, deal_type=deal_type)
        if rec.price is None:      # 가격 없으면 스킵(품절/비정상)
            print(f"  - skip {pid} (no price)", file=sys.stderr)
            continue
        if deal_end_ms and rec.timedeal_end is None:    # 글로벌 딜 마감(개별 타이머 없을 때)
            rec.timedeal_end = deal_end_ms
        yield rec


def crawl(fetcher: Fetcher, query: str, *, category_id: int | None = None,
          deal_type: str = "general", limit: int | None = None):
    ids = discover_ids(fetcher, query, limit)
    print(f"[{query}] {len(ids)} products", file=sys.stderr)
    yield from _fetch_details(fetcher, ids, category_id=category_id, deal_type=deal_type)


def main():
    ap = argparse.ArgumentParser(description="오아시스 식자재 크롤러 → JSONL")
    ap.add_argument("--categories", help="카테고리ID 콤마구분 (예: 11,216,247). 목록은 README 참조")
    ap.add_argument("--deal", choices=["closeSale", "timeSale"],
                    help="딜 크롤: closeSale(마감세일, 매일 17시 오픈) / timeSale(타임세일)")
    ap.add_argument("--limit", type=int, default=None, help="소스당 최대 상품 수")
    ap.add_argument("--out", default="-", help="출력 JSONL 경로 (기본 stdout; --kafka 시 파일 생략)")
    ap.add_argument("--kafka", action="store_true",
                    help="Kafka retail.crawl.raw로 직접 produce (파일 중간단계 없이 스트리밍)")
    ap.add_argument("--interval", type=float, default=MIN_INTERVAL, help="요청 간 최소 간격(초)")
    args = ap.parse_args()
    if not args.categories and not args.deal:
        ap.error("--categories 또는 --deal 중 하나는 필요합니다")

    fetcher = Fetcher(min_interval=args.interval)
    sinks, closers, dests = [], [], []

    # Kafka 싱크 — 크롤하며 레코드별 직접 produce (design.md §7.1: confluent-kafka 크롤러)
    if args.kafka:
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines/stream"))
        from _kafka import producer as _producer, TOPIC_RETAIL_RAW, TOPIC_DEAL_RAW  # 지연 import(파일모드 무의존)
        prod = _producer()

        def kafka_sink(rec):
            d = asdict(rec)
            topic = TOPIC_DEAL_RAW if d.get("deal_type") in ("closeSale", "timeSale") else TOPIC_RETAIL_RAW
            prod.produce(topic, key=f"oasis:{d.get('product_id')}".encode(),
                         value=json.dumps(d, ensure_ascii=False).encode(),
                         headers=[("source", b"oasis")])
            prod.poll(0)
        sinks.append(kafka_sink); closers.append(prod.flush)
        dests.append(f"kafka:{TOPIC_RETAIL_RAW}|{TOPIC_DEAL_RAW}")

    # 파일/stdout 싱크 — 파일(--out) 또는 (kafka 없을 때만) stdout
    write_file = args.out and args.out != "-"
    fh = open(args.out, "w", encoding="utf-8") if write_file else (None if args.kafka else sys.stdout)
    if fh is not None:
        def file_sink(rec):
            fh.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n"); fh.flush()
        sinks.append(file_sink)
        closers.append(fh.close) if fh is not sys.stdout else None
        dests.append(args.out if fh is not sys.stdout else "stdout")

    def dump(rec):
        for s in sinks:
            s(rec)

    n = 0
    try:
        if args.deal:  # 마감/타임세일 = /product/{deal} HTML discovery + 글로벌 마감시각
            ids, end_ms = discover_deal(fetcher, args.deal, args.limit)
            print(f"[{args.deal}] {len(ids)} products (마감 epoch {end_ms})", file=sys.stderr)
            for rec in _fetch_details(fetcher, ids, deal_type=args.deal, deal_end_ms=end_ms):
                dump(rec); n += 1
            if n == 0:
                print(f"[note] '{args.deal}' 0건 — 진행 딜 없음(품절/윈도우 밖).", file=sys.stderr)
        if args.categories:
            for cid in (int(c) for c in args.categories.split(",") if c.strip()):
                for rec in crawl(fetcher, f"categoryId={cid}", category_id=cid,
                                 deal_type="general", limit=args.limit):
                    dump(rec); n += 1
    finally:
        for close in closers:
            close()
    print(f"[done] {n} records → {', '.join(dests)}", file=sys.stderr)
    print(f"FB_POLLER_RECORDS {n}")


if __name__ == "__main__":
    main()
