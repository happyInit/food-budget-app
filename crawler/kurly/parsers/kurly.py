# 마켓컬리 상품 카드 파서 (베스트/할인 페이지 공통 - 카드 구조가 동일하다)
# 카드 구조: (쿠폰/혜택 뱃지) | 담기 버튼 | 배송유형 | 상품명 | 한줄설명 | 가격 정보 | 재고 | (Kurly Only)
# 가격 정보는 할인이 있으면 "정가 -> 할인율 -> 할인가" 3줄, 없으면 가격 1줄만 나온다
import re

# 상품 카드 컨테이너 (지연 로딩이라 크롤러 쪽에서 스크롤 후 호출해야 한다)
ITEM_SELECTOR = "article"

_SITE_ORIGIN = "https://www.kurly.com"
_CART_BUTTON = "담기"
_PRICE_PATTERN = re.compile(r"^([\d,]+)원~?$")
_PERCENT_PATTERN = re.compile(r"^(\d{1,3})%$")
_GOODS_ID_PATTERN = re.compile(r"/goods/(\d+)")

# 상품명 중량/용량 파싱 — 실제 크롤링 데이터(3,315건) 전수조사로 뽑은 단위 어휘.
# item_code 매핑(NER)은 범위 밖: 여기서는 g/mL 정규화까지만 한다 (design.md §6.3 표준 품목 마스터 PoC 몫).
_WEIGHT_UNITS = {"kg": 1000, "g": 1}
_VOLUME_UNITS = {"l": 1000, "ml": 1}
# '300g X 2개입'처럼 낱개중량 x 수량 표기 — 총중량 계산용으로 일반 패턴보다 먼저 확인한다.
_MULTIPLIER_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(kg|g|ml|l)\s*[xX*]\s*(\d+)", re.IGNORECASE
)
_QUANTITY_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(kg|g|ml|l|개입|개|입|봉|팩|마리|단|통|조각|인분|미|구|매|뿌리|송이|알|모|줄|병|캔)",
    re.IGNORECASE,
)
# '(택1)', 'N종'은 여러 변형 중 하나를 고르는 상품이라 중량을 하나로 특정할 수 없다.
_VARIANT_PATTERN = re.compile(r"\d+종|\(?택\d\)?")


def parse_quantity(name: str) -> dict:
    """상품명에서 중량/용량을 뽑아 g·mL 단위로 정규화한다.

    변형선택 상품(N종/택N)은 무게를 특정할 수 없으므로 is_variant_selection만
    표시하고 weight_grams/volume_ml은 비워둔다. 개수 단위(개/입/마리 등)만 있고
    무게 표기가 없는 경우도 마찬가지로 비워둔다 — 표준 품목 마스터 PoC에서
    참조중량으로 보완할 몫이다.
    """
    is_variant = bool(_VARIANT_PATTERN.search(name))

    multiplier_match = _MULTIPLIER_PATTERN.search(name)
    if multiplier_match:
        raw_text = multiplier_match.group(0)
        value = float(multiplier_match.group(1)) * int(multiplier_match.group(3))
        unit = multiplier_match.group(2).lower()
    else:
        quantity_match = _QUANTITY_PATTERN.search(name)
        if not quantity_match:
            return {
                "quantity_raw": None,
                "weight_grams": None,
                "volume_ml": None,
                "is_variant_selection": is_variant,
            }
        raw_text = quantity_match.group(0)
        value = float(quantity_match.group(1))
        unit = quantity_match.group(2).lower()

    return {
        "quantity_raw": raw_text,
        "weight_grams": value * _WEIGHT_UNITS[unit] if unit in _WEIGHT_UNITS else None,
        "volume_ml": value * _VOLUME_UNITS[unit] if unit in _VOLUME_UNITS else None,
        "is_variant_selection": is_variant,
    }


async def _get_card_image_url(card) -> str | None:
    """상품 카드의 실제 이미지 URL을 반환한다.

    lazy load JS는 HTML 속성(src attribute)은 SVG 그대로 두고
    DOM 프로퍼티(img.src)만 실제 URL로 교체한다.
    get_attribute()는 속성을 읽으므로 evaluate()로 프로퍼티를 직접 읽는다.

    페이지 하단 카드는 스크롤 직후라 이미지가 아직 로드 중일 수 있다.
    빈 값이면 뷰포트 안으로 스크롤한 뒤 500ms 대기 후 한 번 더 시도한다.
    """
    img = card.locator("img").first
    src = await img.evaluate("el => el.src") or ""
    if not src or src.startswith("data:"):
        await img.scroll_into_view_if_needed()
        await img.page.wait_for_timeout(500)
        src = await img.evaluate("el => el.src") or ""
    return src if src and not src.startswith("data:") else None


async def extract_raw_items(page) -> list[dict]:
    """페이지에서 후보 항목들의 원본 정보(텍스트/상세링크/이미지)를 가져온다."""
    locator = page.locator(ITEM_SELECTOR)
    count = await locator.count()
    raw_items = []
    for i in range(count):
        card = locator.nth(i)
        raw_items.append({
            "text": await card.inner_text(),
            # 카드를 감싸는 링크가 상세페이지 주소다 (/goods/{product_id})
            "href": await card.locator("a").first.get_attribute("href"),
            "image_url": await _get_card_image_url(card),
        })
    return raw_items


def parse_item(raw_item: dict) -> dict | None:
    """항목 정보 하나를 파싱한다. '담기' 버튼이 없으면 상품 카드가 아니므로 None을 반환한다."""
    href = raw_item.get("href") or ""
    goods_id_match = _GOODS_ID_PATTERN.search(href)
    if not goods_id_match:
        return None
    product_id = goods_id_match.group(1)
    detail_url = _SITE_ORIGIN + href

    lines = [line.strip() for line in raw_item["text"].split("\n") if line.strip()]
    # 품절/재입고대기 카드는 '담기' 대신 'Coming Soon'+'재입고 알림' 버튼이 뜬다.
    # 예산 앱에서 살 수 없는 상품은 의미가 없으므로 의도적으로 제외한다.
    if _CART_BUTTON not in lines:
        return None

    # '담기' 다음 줄부터가 실제 상품 정보다 (그 앞은 쿠폰/혜택 뱃지).
    # 쿠폰은 회원등급·최초가입 등 조건부라 로그인 없는 크롤러 입장에선 적용 여부를
    # 알 수 없다 — 가격은 항상 표시 판매가(sale_price) 기준으로 남기고 쿠폰은 버린다.
    rest = lines[lines.index(_CART_BUTTON) + 1:]
    if not rest:
        return None

    delivery_info = rest[0] if rest[0].endswith("배송") else None
    body = rest[1:] if delivery_info else rest
    if not body:
        return None

    name = body[0]

    prices = []
    discount_rate = None
    for line in body[1:]:
        price_match = _PRICE_PATTERN.match(line)
        if price_match:
            prices.append(int(price_match.group(1).replace(",", "")))
            continue
        percent_match = _PERCENT_PATTERN.match(line)
        if percent_match:
            discount_rate = int(percent_match.group(1))

    if len(prices) >= 2:
        original_price, sale_price = prices[0], prices[1]
    elif len(prices) == 1:
        original_price, sale_price, discount_rate = None, prices[0], None
    else:
        return None

    return {
        "product_id": product_id,
        "detail_url": detail_url,
        "image_url": raw_item.get("image_url"),
        "name": name,
        "original_price": original_price,
        "sale_price": sale_price,
        "discount_rate": discount_rate,
        "delivery_info": delivery_info,
        **parse_quantity(name),
    }


async def parse_page(page) -> list[dict]:
    """현재 페이지에서 상품 목록을 추출해 파싱한다 (지연 로딩이라 호출 전 스크롤 필요)."""
    raw_items = await extract_raw_items(page)
    parsed = (parse_item(raw) for raw in raw_items)
    return [item for item in parsed if item and item["name"]]
