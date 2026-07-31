"""만개의레시피 요리후기 수집 — 대상·결과 모두 DB(PG). CSV 입출력 없음.

대상은 `recipe` 의 만개(source='10K') 레시피에서 직접 뽑고(reparse_buy_link_backfill.py 와
같은 방식), 결과는 `recipe_review`(원문) + `recipe_review_crawl`(시도 결과)로 적재한다.
`(recipe_id, seq)` upsert 라 **여러 번 돌려도 안전(멱등)**.

닉네임은 저장하지 않는다 — 감정분류·요약 어디에도 쓰이지 않는 개인정보라 수집 단계에서 버린다.
파싱(요리후기만 추출, 일반 댓글 제외)은 원본 로직을 그대로 유지한다.

사용:
  python crawler/10k_recipe/review_crawler.py --dry-run --limit 20   # 대상만 확인
  python crawler/10k_recipe/review_crawler.py --limit 50             # 시범 수집
  python crawler/10k_recipe/review_crawler.py                        # 전량
  python crawler/10k_recipe/review_crawler.py --retry-failed         # 실패분만 재시도

스키마: docs/prd/schema-public-data.sql §G
"""
import argparse
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# pipelines/ingest/_db.py 재사용 — .env 에서 PG* 를 읽는 공용 커넥션.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines/ingest"))
from _db import connect as db_connect  # noqa: E402

# =========================================================
# 설정
# =========================================================

BASE_URL = "https://www.10000recipe.com"

MAX_WORKERS = 3
REQUEST_TIMEOUT = 15
REQUEST_DELAY_MIN = 0.6
REQUEST_DELAY_MAX = 1.2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}

write_lock = threading.Lock()   # DB 쓰기 직렬화(커넥션 폭주 방지)
request_lock = threading.Lock()
thread_local = threading.local()


# =========================================================
# 공통 함수
# =========================================================

def clean_text(value):
    if value is None:
        return ""

    text = re.sub(r"\s+", " ", str(value)).strip()

    # 사이트 UI 문구 정리
    remove_patterns = [
        r"^리뷰별점\s*",
        r"\s*리뷰별점$",
        r"^프로필 사진\s*",
        r"^신고\s*$",
        r"^답글\s*$",
    ]

    for pattern in remove_patterns:
        text = re.sub(pattern, "", text).strip()

    return text


def looks_like_date(text):
    return bool(
        re.search(
            r"\b20\d{2}[-./]\d{1,2}[-./]\d{1,2}"
            r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?\b",
            text,
        )
    )


def is_invalid_nickname(text):
    if not text:
        return True

    invalid_values = {
        "리뷰별점",
        "포토 후기",
        "요리후기",
        "전체보기",
        "더보기",
        "신고",
        "답글",
        "댓글",
        "만개레시피닉네임",
    }

    if text in invalid_values:
        return True

    if looks_like_date(text):
        return True

    if len(text) > 80:
        return True

    return False


def is_invalid_review_text(text):
    if not text:
        return True

    invalid_values = {
        "아직 후기가 없습니다.",
        "전체보기",
        "더보기",
        "리뷰별점",
        "신고",
        "답글",
    }

    if text in invalid_values:
        return True

    if looks_like_date(text) and len(text) < 30:
        return True

    return False


# =========================================================
# HTTP 세션
# =========================================================

def create_session():
    session = requests.Session()

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=MAX_WORKERS,
        pool_maxsize=MAX_WORKERS,
    )

    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(HEADERS)

    return session


def get_session():
    if not hasattr(thread_local, "session"):
        thread_local.session = create_session()

    return thread_local.session


def request_page(url):
    with request_lock:
        time.sleep(
            random.uniform(
                REQUEST_DELAY_MIN,
                REQUEST_DELAY_MAX,
            )
        )

    response = get_session().get(
        url,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    return response


# =========================================================
# CSV 처리
# =========================================================

def load_recipe_targets(limit=None, retry_failed=False):
    """DB의 만개(10K) 레시피를 대상으로 삼는다 — CSV 입력 없음.

    이미 시도한 레시피(recipe_review_crawl 에 행이 있는 것)는 건너뛴다. 리뷰 0건도
    기록되므로 재실행 시 반복 요청이 나가지 않는다.

    --retry-failed 는 **미시도 + status='fail'** 을 대상으로 삼는다(일시적 네트워크 실패
    복구용). 전량 수집이 끝난 뒤에는 미시도가 0이라 사실상 실패분만 남는다.
    ⚠️ 성공(ok)·리뷰없음(no_review)은 어느 모드에서도 재크롤하지 않는다 — 만개에 불필요한
       요청을 보내지 않기 위한 선이다.
    """
    # 미시도(c.recipe_id is null)가 기본. --retry-failed 면 직전 실패분까지 포함한다.
    # ⚠️ 조인 조건이 아니라 WHERE 로 걸러야 한다 — LEFT JOIN 의 ON 절에 상태를 넣으면
    #    매칭만 실패할 뿐 행이 남아 전체 레시피가 대상이 된다(재크롤 폭주).
    pending = "(c.recipe_id is null or c.status = 'fail')" if retry_failed else "c.recipe_id is null"
    sql = f"""
        select r.id, r.src_recipe_id
          from recipe r
          left join recipe_review_crawl c on c.recipe_id = r.id
         where r.source = '10K'
           and r.src_recipe_id is not null
           and {pending}
         order by r.id
    """
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    targets = [
        {
            "recipe_pk": pk,
            "레시피ID": src,
            "레시피URL": f"{BASE_URL}/recipe/{src}",
        }
        for pk, src in rows
    ]
    return targets[:limit] if limit else targets


def save_reviews(recipe_pk, reviews):
    """원문 저장 — (recipe_id, seq) upsert 라 여러 번 돌려도 안전. 닉네임은 버린다."""
    with db_connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """insert into recipe_review (recipe_id, seq, body)
               values (%s, %s, %s)
               on conflict (recipe_id, seq)
               do update set body = excluded.body, fetched_at = now()""",
            [(recipe_pk, i, r["content"]) for i, r in enumerate(reviews, start=1)],
        )
        conn.commit()


def save_crawl_status(recipe_pk, status, reason=None, review_count=0):
    """시도 결과 기록 — 리뷰 0건·실패도 남겨 재실행 시 반복 요청을 막는다."""
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute(
            """insert into recipe_review_crawl (recipe_id, status, reason, review_count)
               values (%s, %s, %s, %s)
               on conflict (recipe_id) do update
                 set status = excluded.status, reason = excluded.reason,
                     review_count = excluded.review_count, attempted_at = now()""",
            (recipe_pk, status, reason, review_count),
        )
        conn.commit()


# =========================================================
# 리뷰 추출
# =========================================================

def find_text_by_selectors(card, selectors):
    for selector in selectors:
        node = card.select_one(selector)

        if node:
            text = clean_text(
                node.get_text(" ", strip=True)
            )

            if text:
                return text

    return ""


def parse_review_cards_by_css(soup):
    """
    사이트 구조가 변경되는 경우를 고려해 여러 리뷰 카드 선택자를 시도합니다.
    """
    card_selectors = [
        ".view_reply .media",
        ".view_reply_list .media",
        ".view_review .media",
        ".review_list .media",
        ".review_list li",
        ".reply_list .media",
        ".reply_list li",
        ".view_reply li",
        "[class*='review'] .media",
        "[class*='review'] li",
    ]

    nickname_selectors = [
        ".media-heading",
        ".review_name",
        ".review_user",
        ".reply_name",
        ".name",
        "strong",
        "h4",
        "h5",
    ]

    content_selectors = [
        ".review_content",
        ".review_text",
        ".reply_content",
        ".reply_text",
        ".media-body p",
        ".media-body",
        "p",
    ]

    reviews = []
    seen = set()

    for card_selector in card_selectors:
        cards = soup.select(card_selector)

        if not cards:
            continue

        for card in cards:
            nickname = find_text_by_selectors(
                card,
                nickname_selectors,
            )
            review_text = find_text_by_selectors(
                card,
                content_selectors,
            )

            # media-body 전체가 잡힌 경우 닉네임/날짜/UI 문구 제거
            if review_text:
                review_text = re.sub(
                    r"\b20\d{2}[-./]\d{1,2}[-./]\d{1,2}"
                    r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?\b",
                    " ",
                    review_text,
                )
                review_text = review_text.replace(
                    nickname,
                    " ",
                    1,
                )
                review_text = re.sub(
                    r"\b리뷰별점\b|\b신고\b|\b답글\b",
                    " ",
                    review_text,
                )
                review_text = clean_text(review_text)

            if is_invalid_nickname(nickname):
                continue

            if is_invalid_review_text(review_text):
                continue

            key = (nickname, review_text)

            if key in seen:
                continue

            seen.add(key)
            reviews.append({
                "nickname": nickname,
                "content": review_text,
            })

        if reviews:
            return reviews

    return reviews


def parse_reviews_from_headings(soup):
    """
    후기 DOM이 제목(닉네임+날짜)과 본문으로 구성된 경우를 처리합니다.
    검색엔진에서 확인되는 상세 페이지 구조에 대한 보조 파서입니다.
    """
    reviews = []
    seen = set()

    heading_nodes = soup.select(
        "h3, h4, h5, strong, .media-heading"
    )

    heading_pattern = re.compile(
        r"^(?P<nickname>.+?)\s+"
        r"20\d{2}[-./]\d{1,2}[-./]\d{1,2}"
        r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?$"
    )

    for heading in heading_nodes:
        heading_text = clean_text(
            heading.get_text(" ", strip=True)
        )

        match = heading_pattern.match(heading_text)

        if not match:
            continue

        nickname = clean_text(
            match.group("nickname")
        )

        if is_invalid_nickname(nickname):
            continue

        review_text = ""

        # 제목 다음의 실제 후기 본문 후보 탐색
        sibling = heading.find_next_sibling()

        search_count = 0

        while sibling is not None and search_count < 5:
            search_count += 1

            if isinstance(sibling, Tag):
                candidate = clean_text(
                    sibling.get_text(" ", strip=True)
                )

                if (
                    candidate
                    and not looks_like_date(candidate)
                    and not is_invalid_review_text(candidate)
                    and candidate != nickname
                ):
                    review_text = candidate
                    break

            sibling = sibling.find_next_sibling()

        # 직접 형제에서 못 찾으면 부모 요소 안에서 본문 탐색
        if not review_text:
            parent = heading.parent

            if parent:
                parent_text = clean_text(
                    parent.get_text(" ", strip=True)
                )

                parent_text = parent_text.replace(
                    heading_text,
                    " ",
                    1,
                )
                parent_text = re.sub(
                    r"\b리뷰별점\b|\b신고\b|\b답글\b",
                    " ",
                    parent_text,
                )
                review_text = clean_text(parent_text)

        if is_invalid_review_text(review_text):
            continue

        key = (nickname, review_text)

        if key in seen:
            continue

        seen.add(key)
        reviews.append({
            "nickname": nickname,
            "content": review_text,
        })

    return reviews


def parse_reviews_from_plain_text(soup):
    """
    CSS 구조를 찾지 못했을 때 페이지 텍스트에서
    '닉네임 + 날짜 + 리뷰 본문' 패턴을 찾는 최종 보조 파서입니다.
    """
    text = soup.get_text("\n", strip=True)

    lines = [
        clean_text(line)
        for line in text.splitlines()
        if clean_text(line)
    ]

    date_pattern = re.compile(
        r"^20\d{2}[-./]\d{1,2}[-./]\d{1,2}"
        r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?$"
    )

    reviews = []
    seen = set()

    for index, line in enumerate(lines):
        # 형태 1: "닉네임 2021-12-16 19:06:44"
        combined_match = re.match(
            r"^(?P<nickname>.+?)\s+"
            r"20\d{2}[-./]\d{1,2}[-./]\d{1,2}"
            r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?$",
            line,
        )

        if combined_match:
            nickname = clean_text(
                combined_match.group("nickname")
            )
            content_start = index + 1

        # 형태 2: 닉네임과 날짜가 서로 다른 줄
        elif (
            index + 1 < len(lines)
            and date_pattern.match(lines[index + 1])
        ):
            nickname = line
            content_start = index + 2

        else:
            continue

        if is_invalid_nickname(nickname):
            continue

        review_parts = []

        for content_index in range(
            content_start,
            min(content_start + 8, len(lines)),
        ):
            candidate = lines[content_index]

            if date_pattern.match(candidate):
                break

            if re.match(
                r"^.+?\s+20\d{2}[-./]\d{1,2}[-./]\d{1,2}",
                candidate,
            ):
                break

            if candidate in {
                "전체보기",
                "더보기",
                "리뷰별점",
                "신고",
                "답글",
            }:
                continue

            if candidate.startswith("요리후기"):
                break

            review_parts.append(candidate)

            # 보통 리뷰 본문은 한두 블록이므로 과수집 방지
            if len(" ".join(review_parts)) >= 500:
                break

        review_text = clean_text(
            " ".join(review_parts)
        )

        if is_invalid_review_text(review_text):
            continue

        key = (nickname, review_text)

        if key in seen:
            continue

        seen.add(key)
        reviews.append({
            "nickname": nickname,
            "content": review_text,
        })

    return reviews


def extract_reviews(soup):
    """
    요리후기만 추출합니다.
    일반 댓글 영역은 최대한 제외합니다.
    """
    page_text = clean_text(
        soup.get_text(" ", strip=True)
    )

    if (
        "요리후기0" in page_text
        or "아직 후기가 없습니다." in page_text
    ):
        return []

    parsers = [
        parse_review_cards_by_css,
        parse_reviews_from_headings,
        parse_reviews_from_plain_text,
    ]

    for parser in parsers:
        reviews = parser(soup)

        if reviews:
            return reviews

    return []


# =========================================================
# 레시피별 리뷰 수집
# =========================================================

def fetch_reviews(target):
    recipe_id = target["레시피ID"]
    recipe_url = target["레시피URL"]

    if not recipe_url:
        return {
            "status": "fail",
            "recipe_id": recipe_id,
            "recipe_url": "",
            "reason": "RECIPE_URL_MISSING",
            "reviews": [],
        }

    try:
        response = request_page(recipe_url)
        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        page_text = clean_text(
            soup.get_text(" ", strip=True)
        )

        no_review = (
            "요리후기0" in page_text
            or "아직 후기가 없습니다." in page_text
        )

        reviews = extract_reviews(soup)

        if reviews:
            return {
                "status": "success",
                "recipe_id": recipe_id,
                "recipe_url": recipe_url,
                "reviews": reviews,
            }

        if no_review:
            return {
                "status": "no_review",
                "recipe_id": recipe_id,
                "recipe_url": recipe_url,
                "reviews": [],
            }

        return {
            "status": "fail",
            "recipe_id": recipe_id,
            "recipe_url": recipe_url,
            "reason": "REVIEW_NOT_PARSED",
            "reviews": [],
        }

    except requests.HTTPError as error:
        status_code = (
            error.response.status_code
            if error.response is not None
            else "UNKNOWN"
        )

        return {
            "status": "fail",
            "recipe_id": recipe_id,
            "recipe_url": recipe_url,
            "reason": f"HTTP_ERROR_{status_code}",
            "reviews": [],
        }

    except requests.RequestException:
        return {
            "status": "fail",
            "recipe_id": recipe_id,
            "recipe_url": recipe_url,
            "reason": "REQUEST_ERROR",
            "reviews": [],
        }

    except Exception as error:
        return {
            "status": "fail",
            "recipe_id": recipe_id,
            "recipe_url": recipe_url,
            "reason": f"PARSING_ERROR: {error}",
            "reviews": [],
        }


# =========================================================
# 메인
# =========================================================

def main():
    ap = argparse.ArgumentParser(description="만개 요리후기 수집 — DB 기반(입력·출력 모두 PG)")
    ap.add_argument("--limit", type=int, help="상위 N건만 처리(시범 실행)")
    ap.add_argument("--dry-run", action="store_true", help="대상만 출력하고 종료")
    ap.add_argument("--retry-failed", action="store_true",
                    help="status='fail' 만 재시도(리뷰 0건은 건너뜀)")
    args = ap.parse_args()

    pending_targets = load_recipe_targets(args.limit, args.retry_failed)

    print("=" * 72)
    print("만개의레시피 요리후기 수집기 (DB)")
    print("=" * 72)
    print(f"이번 실행 대상: {len(pending_targets)}개")

    if args.dry_run or not pending_targets:
        for t in pending_targets[:20]:
            print(f"  {t['레시피URL']}")
        if len(pending_targets) > 20:
            print(f"  … 외 {len(pending_targets) - 20}건")
        return

    recipe_success_count = no_review_count = fail_count = total_review_count = 0

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_map = {
                executor.submit(fetch_reviews, target): target
                for target in pending_targets
            }

            for index, future in enumerate(as_completed(future_map), start=1):
                result = future.result()
                pk = future_map[future]["recipe_pk"]

                with write_lock:
                    if result["status"] == "success":
                        save_reviews(pk, result["reviews"])
                        save_crawl_status(pk, "ok", review_count=len(result["reviews"]))
                        recipe_success_count += 1
                        total_review_count += len(result["reviews"])
                    elif result["status"] == "no_review":
                        save_crawl_status(pk, "no_review")
                        no_review_count += 1
                    else:
                        save_crawl_status(pk, "fail", reason=result.get("reason"))
                        fail_count += 1

                if index % 10 == 0 or index == len(pending_targets):
                    print(f"[{index}/{len(pending_targets)}] "
                          f"리뷰 발견 {recipe_success_count}, 리뷰 없음 {no_review_count}, "
                          f"실패 {fail_count}, 누적 리뷰 {total_review_count}")

    except KeyboardInterrupt:
        print("\n사용자 중단 — 이미 저장된 레시피는 재실행 시 자동으로 건너뜁니다.")

    finally:
        print("\n" + "=" * 72)
        print(f"리뷰 발견 레시피: {recipe_success_count}")
        print(f"리뷰 없는 레시피: {no_review_count}")
        print(f"추출 실패 레시피: {fail_count}")
        print(f"수집 리뷰 수: {total_review_count}")
        print(f"FB_POLLER_RECORDS {total_review_count}")


if __name__ == "__main__":
    main()
