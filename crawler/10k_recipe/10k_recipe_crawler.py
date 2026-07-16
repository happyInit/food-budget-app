import argparse
import csv
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# =========================================================
# 기본 설정
# =========================================================

BASE_URL = "https://www.10000recipe.com"

OFFICIAL_FILE = "공식_레시피.csv"
GENERAL_FILE = "일반_검증완료_레시피.csv"
INGREDIENT_FILE = "레시피_재료.csv"
REJECT_FILE = "제외_레시피.csv"
STATE_FILE = "크롤링_상태.json"

TARGET_TOTAL_COUNT = 10000
MAX_LIST_PAGES = 1000
MAX_WORKERS = 3

REQUEST_TIMEOUT = 15
REQUEST_DELAY_MIN = 0.6
REQUEST_DELAY_MAX = 1.2

MIN_INGREDIENTS = 1
MIN_STEPS = 1

OFFICIAL_AUTHORS = {
    "만개의레시피"
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8"
}

CSV_COLUMNS = [
    "레시피ID",
    "레시피URL",
    "썸네일URL",
    "제목",
    "요약",
    "인원",
    "시간",
    "난이도",
    "재료",
    "재료개수",
    "조리순서",
    "조리단계수",
    "태그",
    "작성자",
    "작성자구분",
    "품질점수",
    "데이터검증상태",
    "수집일시"
]

INGREDIENT_COLUMNS = [
    "레시피ID",
    "레시피URL",
    "재료순번",
    "재료그룹",
    "재료명",
    "수량",
    "재료원문",
    "작성자구분",
    "수집일시"
]

REJECT_COLUMNS = [
    "레시피URL",
    "제외사유",
    "확인일시"
]


# =========================================================
# 전역 상태
# =========================================================

csv_lock = threading.Lock()
request_lock = threading.Lock()
thread_local = threading.local()

processed_urls = set()
rejected_urls = set()

official_count = 0
general_count = 0
reject_count = 0

# Kafka 싱크 (--kafka). 상태·CSV는 resume/dedup 참고용, 실 적재는 Kafka→recipe-refiner→PG.
_producer = None
_topic = None
kafka_produced = 0


def init_kafka():
    """--kafka 시 pipelines/stream 프로듀서 지연 로드(파일모드 무의존). recipe.crawl.raw로 발행."""
    global _producer, _topic
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines/stream"))
    from _kafka import producer, TOPIC_RECIPE_RAW  # noqa: E402
    _producer = producer()
    _topic = TOPIC_RECIPE_RAW


def build_stream_record(data, ingredients, steps):
    """검증 레시피 → recipe.crawl.raw nested record (load_10k_recipe.process_recipe 소비형과 1:1).
    steps=원문 리스트, ingredients=[{seq,name,quantity,raw}], image_url=썸네일(og:image)."""
    return {
        "src_recipe_id": data["레시피ID"],
        "name": data["제목"],
        "cooking_time": data.get("시간"),
        "level_nm": data.get("난이도"),
        "serving": data.get("인원"),
        "image_url": data.get("썸네일URL"),
        "steps": steps,
        "ingredients": [
            {"seq": i, "name": ing.get("name", ""),
             "quantity": ing.get("amount", ""), "raw": ing.get("raw_text", "")}
            for i, ing in enumerate(ingredients, start=1)
        ],
    }


def produce_record(data, ingredients, steps):
    """레시피 1건 → Kafka produce (멱등: 컨슈머가 source,src_recipe_id upsert). csv_lock 하에서 호출."""
    global kafka_produced
    rec = build_stream_record(data, ingredients, steps)
    _producer.produce(
        _topic,
        key=f"10K:{rec['src_recipe_id']}".encode(),
        value=json.dumps(rec, ensure_ascii=False).encode(),
        headers=[("source", b"10K")],
    )
    _producer.poll(0)
    kafka_produced += 1


# =========================================================
# 공통 유틸리티
# =========================================================

def clean_text(text):
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def now_string():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def extract_recipe_id(url):
    match = re.search(r"/recipe/(\d+)", url)
    return match.group(1) if match else ""


def normalize_recipe_url(href):
    if not href:
        return None

    absolute_url = urljoin(BASE_URL, href)
    match = re.search(r"/recipe/(\d+)", absolute_url)

    if not match:
        return None

    return f"{BASE_URL}/recipe/{match.group(1)}"


def make_ingredient_summary(ingredients):
    summaries = []

    for ingredient in ingredients:
        summary = clean_text(
            f"{ingredient.get('name', '')} "
            f"{ingredient.get('amount', '')}"
        )
        if summary:
            summaries.append(summary)

    return ", ".join(summaries)


def calculate_quality_score(
    title,
    summary,
    serving,
    cooking_time,
    difficulty,
    ingredients,
    steps,
    tags,
    is_official
):
    score = 0

    if title:
        score += 10
    if summary:
        score += 5
    if ingredients:
        score += 20
    if len(ingredients) >= 3:
        score += 10
    if len(ingredients) >= 5:
        score += 5
    if steps:
        score += 20
    if len(steps) >= 3:
        score += 10
    if len(steps) >= 5:
        score += 5
    if serving:
        score += 3
    if cooking_time:
        score += 3
    if difficulty:
        score += 2
    if tags:
        score += 2
    if is_official:
        score += 5

    amount_count = sum(
        1 for ingredient in ingredients
        if ingredient.get("amount")
    )

    if ingredients:
        amount_ratio = amount_count / len(ingredients)
        if amount_ratio >= 0.8:
            score += 5
        elif amount_ratio >= 0.5:
            score += 3

    return min(score, 100)


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
        respect_retry_after_header=True
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=MAX_WORKERS,
        pool_maxsize=MAX_WORKERS
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
                REQUEST_DELAY_MAX
            )
        )

    response = get_session().get(
        url,
        timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response


# =========================================================
# CSV 및 상태 파일
# =========================================================

def append_csv_row(file_name, columns, row):
    file_exists = os.path.exists(file_name)

    with open(
        file_name,
        "a",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=columns,
            extrasaction="ignore"
        )

        if not file_exists:
            writer.writeheader()

        writer.writerow(row)
        file.flush()


def load_existing_urls(file_name):
    urls = set()

    if not os.path.exists(file_name):
        return urls

    with open(
        file_name,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            url = row.get("레시피URL", "").strip()
            if url:
                urls.add(url)

    return urls


def load_state():
    default_state = {
        "last_completed_page": 0,
        "official_count": 0,
        "general_count": 0,
        "reject_count": 0
    }

    if not os.path.exists(STATE_FILE):
        return default_state

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            state = json.load(file)

        return {
            "last_completed_page": state.get("last_completed_page", 0),
            "official_count": state.get("official_count", 0),
            "general_count": state.get("general_count", 0),
            "reject_count": state.get("reject_count", 0)
        }

    except (json.JSONDecodeError, OSError):
        return default_state


def save_state(last_completed_page):
    state = {
        "last_completed_page": last_completed_page,
        "official_count": official_count,
        "general_count": general_count,
        "reject_count": reject_count,
        "updated_at": now_string()
    }

    temp_file = f"{STATE_FILE}.tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temp_file, STATE_FILE)


# =========================================================
# 추천순 목록 페이지
# =========================================================

def get_recipe_links(page_num):
    list_url = (
        f"{BASE_URL}/recipe/list.html"
        f"?order=reco&page={page_num}"
    )

    try:
        response = request_page(list_url)
        soup = BeautifulSoup(response.text, "html.parser")

        links = []
        page_seen = set()

        selectors = [
            "a.common_sp_link",
            ".common_sp_list_li a[href*='/recipe/']",
            ".common_sp_list_ul a[href*='/recipe/']",
            "a[href*='/recipe/']"
        ]

        for selector in selectors:
            nodes = soup.select(selector)

            for node in nodes:
                recipe_url = normalize_recipe_url(
                    node.get("href")
                )

                if not recipe_url:
                    continue

                if recipe_url in page_seen:
                    continue

                page_seen.add(recipe_url)
                links.append(recipe_url)

            if links:
                break

        return links

    except requests.RequestException as error:
        print(f"[목록 요청 실패] 페이지 {page_num}: {error}")
        return []

    except Exception as error:
        print(f"[목록 파싱 실패] 페이지 {page_num}: {error}")
        return []


# =========================================================
# 상세 페이지 추출
# =========================================================

def extract_author(soup):
    selectors = [
        ".profile_cont p a",
        ".profile_cont a",
        ".view2_summary .profile_cont a",
        "[class*='profile'] a[href*='/profile/']",
        "[class*='profile'] a"
    ]

    for selector in selectors:
        node = soup.select_one(selector)

        if not node:
            continue

        author = clean_text(
            node.get_text(" ", strip=True)
        )

        author = re.sub(
            r"^by\s*",
            "",
            author,
            flags=re.I
        )

        if author:
            return author

    return ""


def extract_summary_info(soup):
    info_nodes = soup.select(
        ".view2_summary_info span"
    )

    serving = ""
    cooking_time = ""
    difficulty = ""

    for node in info_nodes:
        text = clean_text(
            node.get_text(" ", strip=True)
        )
        classes = " ".join(node.get("class", []))

        if "info1" in classes:
            serving = text
        elif "info2" in classes:
            cooking_time = text
        elif "info3" in classes:
            difficulty = text

    if not serving and len(info_nodes) > 0:
        serving = clean_text(
            info_nodes[0].get_text(" ", strip=True)
        )

    if not cooking_time and len(info_nodes) > 1:
        cooking_time = clean_text(
            info_nodes[1].get_text(" ", strip=True)
        )

    if not difficulty and len(info_nodes) > 2:
        difficulty = clean_text(
            info_nodes[2].get_text(" ", strip=True)
        )

    return serving, cooking_time, difficulty


def split_ingredient_text(raw_text):
    """
    선택자로 이름/수량을 분리하지 못했을 때 사용하는 보조 함수입니다.
    """
    raw_text = clean_text(raw_text)

    amount_pattern = re.compile(
        r"""
        (
            \d+(?:\.\d+)? |
            \d+/\d+ |
            \d+\s*~\s*\d+ |
            약간|적당량|조금|소량|한줌|한\s*줌
        )
        \s*
        (
            g|kg|ml|l|
            개|봉|팩|모|대|쪽|알|장|줄|
            컵|숟가락|큰술|작은술|티스푼|
            꼬집|줌|조각|토막|마리|근|공기|인분
        )?
        $
        """,
        re.VERBOSE | re.IGNORECASE
    )

    match = amount_pattern.search(raw_text)

    if not match:
        return raw_text, ""

    amount = clean_text(match.group(0))
    name = clean_text(raw_text[:match.start()])

    if not name:
        return raw_text, ""

    return name, amount


def extract_ingredients(soup):
    """
    반환 예시:
    [
        {
            "name": "김치",
            "amount": "300g",
            "raw_text": "김치 300g",
            "group": "재료"
        }
    ]
    """
    ingredient_section = soup.select_one(
        ".ready_ingre3, "
        "[class*='ready_ingre']"
    )

    if ingredient_section is None:
        return False, []

    ingredients = []
    current_group = "재료"

    # 그룹명 후보 수집
    group_nodes = ingredient_section.select(
        "b, strong, dt, h4, h5"
    )

    if group_nodes:
        group_text = clean_text(
            group_nodes[0].get_text(" ", strip=True)
        )
        if group_text:
            current_group = group_text

    for item in ingredient_section.select("li"):
        raw_copy = BeautifulSoup(
            str(item),
            "html.parser"
        )

        for removable in raw_copy.select(
            "button, script, style"
        ):
            removable.decompose()

        for link in raw_copy.select("a"):
            link.unwrap()

        raw_text = clean_text(
            raw_copy.get_text(" ", strip=True)
        )

        raw_text = re.sub(
            r"\s*구매\s*$",
            "",
            raw_text
        ).strip()

        if not raw_text:
            continue

        if len(raw_text) > 200:
            continue

        # 재료명: a 태그 우선
        name_node = item.select_one("a")
        name = (
            clean_text(
                name_node.get_text(" ", strip=True)
            )
            if name_node
            else ""
        )

        # 수량: span 텍스트 우선
        amount = ""
        span_nodes = item.select("span")

        if span_nodes:
            span_texts = [
                clean_text(
                    node.get_text(" ", strip=True)
                )
                for node in span_nodes
            ]
            span_texts = [
                text for text in span_texts
                if text and "구매" not in text
            ]
            if span_texts:
                amount = span_texts[-1]

        # 선택자로 분리 실패 시 원문 기반 보조 분리
        if not name:
            name, fallback_amount = split_ingredient_text(
                raw_text
            )

            if not amount:
                amount = fallback_amount

        # 수량이 재료명까지 포함하면 이름 제거
        if name and amount.startswith(name):
            amount = clean_text(
                amount[len(name):]
            )

        if not name:
            continue

        ingredients.append({
            "name": name,
            "amount": amount,
            "raw_text": raw_text,
            "group": current_group
        })

    unique_ingredients = []
    seen = set()

    for ingredient in ingredients:
        key = (
            ingredient["name"],
            ingredient["amount"],
            ingredient["group"]
        )

        if key in seen:
            continue

        seen.add(key)
        unique_ingredients.append(ingredient)

    return True, unique_ingredients


def extract_steps(soup):
    selectors = [
        ".view_step_cont .media-body",
        "[id^='stepdescr']",
        ".view_step_cont"
    ]

    for selector in selectors:
        nodes = soup.select(selector)

        if not nodes:
            continue

        steps = []

        for node in nodes:
            text = clean_text(
                node.get_text(" ", strip=True)
            )

            if not text:
                continue

            if text in {
                "조리순서",
                "이미지 크게보기",
                "텍스트만 보기",
                "이미지 작게보기"
            }:
                continue

            if len(text) > 3000:
                continue

            steps.append(text)

        if steps:
            return list(dict.fromkeys(steps))

    return []


def extract_thumbnail_url(soup):
    """대표 썸네일 URL(recipe.image_url). og:image → twitter:image → 상세 이미지 선택자 폴백.
    (구 recipe_thumbnail_backfill.py 병합 — 상세페이지 재요청 없이 같은 파싱에서 추출)."""
    for selector in (
        "meta[property='og:image']",
        "meta[name='twitter:image']",
        "meta[property='twitter:image']",
    ):
        node = soup.select_one(selector)
        if node:
            url = clean_text(node.get("content"))
            if url:
                return urljoin(BASE_URL, url)

    for selector in (
        ".centeredcrop img",
        ".view2_pic img",
        ".view2_summary img",
        ".common_sp_thumb img",
    ):
        node = soup.select_one(selector)
        if node:
            url = clean_text(
                node.get("src")
                or node.get("data-src")
                or node.get("data-original")
                or ""
            )
            if url:
                return urljoin(BASE_URL, url)

    return ""


def crawl_recipe_detail(recipe_url):
    try:
        response = request_page(recipe_url)
        soup = BeautifulSoup(response.text, "html.parser")

        title_node = soup.select_one(
            ".view2_summary h3"
        )

        title = (
            clean_text(
                title_node.get_text(" ", strip=True)
            )
            if title_node
            else ""
        )

        summary_node = soup.select_one(
            ".view2_summary_in"
        )

        summary = (
            clean_text(
                summary_node.get_text(" ", strip=True)
            )
            if summary_node
            else ""
        )

        author = extract_author(soup)
        serving, cooking_time, difficulty = (
            extract_summary_info(soup)
        )

        ingredient_section_exists, ingredients = (
            extract_ingredients(soup)
        )

        steps = extract_steps(soup)

        if not title:
            return {
                "valid": False,
                "url": recipe_url,
                "reason": "TITLE_MISSING"
            }

        if not author:
            return {
                "valid": False,
                "url": recipe_url,
                "reason": "AUTHOR_MISSING"
            }

        if not ingredient_section_exists:
            return {
                "valid": False,
                "url": recipe_url,
                "reason": "INGREDIENT_SECTION_MISSING"
            }

        if len(ingredients) < MIN_INGREDIENTS:
            return {
                "valid": False,
                "url": recipe_url,
                "reason": "INGREDIENTS_MISSING"
            }

        if len(steps) < MIN_STEPS:
            return {
                "valid": False,
                "url": recipe_url,
                "reason": "STEPS_MISSING"
            }

        tags = [
            clean_text(
                node.get_text(" ", strip=True)
            )
            for node in soup.select(".view_tag a")
        ]
        tags = [tag for tag in tags if tag]

        is_official = author in OFFICIAL_AUTHORS

        quality_score = calculate_quality_score(
            title=title,
            summary=summary,
            serving=serving,
            cooking_time=cooking_time,
            difficulty=difficulty,
            ingredients=ingredients,
            steps=steps,
            tags=tags,
            is_official=is_official
        )

        data = {
            "레시피ID": extract_recipe_id(recipe_url),
            "레시피URL": recipe_url,
            "썸네일URL": extract_thumbnail_url(soup),
            "제목": title,
            "요약": summary,
            "인원": serving,
            "시간": cooking_time,
            "난이도": difficulty,
            "재료": make_ingredient_summary(ingredients),
            "재료개수": len(ingredients),
            "조리순서": "\n".join(
                f"{index}. {step}"
                for index, step in enumerate(
                    steps,
                    start=1
                )
            ),
            "조리단계수": len(steps),
            "태그": ", ".join(tags),
            "작성자": author,
            "작성자구분": (
                "OFFICIAL"
                if is_official
                else "GENERAL"
            ),
            "품질점수": quality_score,
            "데이터검증상태": "VALID",
            "수집일시": now_string()
        }

        return {
            "valid": True,
            "official": is_official,
            "data": data,
            "ingredients": ingredients,
            "steps": steps
        }

    except requests.HTTPError as error:
        status_code = (
            error.response.status_code
            if error.response is not None
            else "UNKNOWN"
        )

        return {
            "valid": False,
            "url": recipe_url,
            "reason": f"HTTP_ERROR_{status_code}"
        }

    except requests.RequestException:
        return {
            "valid": False,
            "url": recipe_url,
            "reason": "REQUEST_ERROR"
        }

    except Exception as error:
        print(f"[상세 파싱 오류] {recipe_url}: {error}")

        return {
            "valid": False,
            "url": recipe_url,
            "reason": "PARSING_ERROR"
        }


# =========================================================
# 저장
# =========================================================

def save_ingredients(recipe_data, ingredients):
    for index, ingredient in enumerate(
        ingredients,
        start=1
    ):
        append_csv_row(
            INGREDIENT_FILE,
            INGREDIENT_COLUMNS,
            {
                "레시피ID": recipe_data["레시피ID"],
                "레시피URL": recipe_data["레시피URL"],
                "재료순번": index,
                "재료그룹": ingredient.get("group", "재료"),
                "재료명": ingredient.get("name", ""),
                "수량": ingredient.get("amount", ""),
                "재료원문": ingredient.get("raw_text", ""),
                "작성자구분": recipe_data["작성자구분"],
                "수집일시": recipe_data["수집일시"]
            }
        )


def save_result(result):
    global official_count
    global general_count
    global reject_count

    if not result["valid"]:
        recipe_url = result["url"]

        with csv_lock:
            if recipe_url in rejected_urls:
                return

            append_csv_row(
                REJECT_FILE,
                REJECT_COLUMNS,
                {
                    "레시피URL": recipe_url,
                    "제외사유": result["reason"],
                    "확인일시": now_string()
                }
            )

            rejected_urls.add(recipe_url)
            reject_count += 1

        return

    data = result["data"]
    ingredients = result["ingredients"]
    recipe_url = data["레시피URL"]

    with csv_lock:
        if recipe_url in processed_urls:
            return

        # 재료 저장
        save_ingredients(
            recipe_data=data,
            ingredients=ingredients
        )

        # 레시피 저장
        if result["official"]:
            append_csv_row(
                OFFICIAL_FILE,
                CSV_COLUMNS,
                data
            )
            official_count += 1
            category = "공식"
        else:
            append_csv_row(
                GENERAL_FILE,
                CSV_COLUMNS,
                data
            )
            general_count += 1
            category = "일반"

        processed_urls.add(recipe_url)

        if _producer is not None:      # 신규 저장분만 Kafka로(=참고 CSV와 동일 대상, 중복 X)
            produce_record(data, ingredients, result.get("steps") or [])

        total_count = official_count + general_count

        print(
            f"[{category}] "
            f"전체 {total_count}/{TARGET_TOTAL_COUNT} | "
            f"공식 {official_count} | "
            f"일반 {general_count} | "
            f"재료 {len(ingredients)}개 | "
            f"점수 {data['품질점수']} | "
            f"{data['제목']}"
        )


# =========================================================
# 페이지 단위 스트리밍 처리
# =========================================================

def process_page(page_num):
    links = get_recipe_links(page_num)

    if not links:
        return 0

    new_links = [
        link
        for link in links
        if link not in processed_urls
        and link not in rejected_urls
    ]

    print(
        f"\n페이지 {page_num}: "
        f"목록 {len(links)}개, "
        f"신규 {len(new_links)}개"
    )

    if not new_links:
        return len(links)

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_map = {
            executor.submit(
                crawl_recipe_detail,
                link
            ): link
            for link in new_links
        }

        for future in as_completed(future_map):
            result = future.result()
            save_result(result)

            if (
                official_count + general_count
                >= TARGET_TOTAL_COUNT
            ):
                break

    return len(links)


# =========================================================
# 메인
# =========================================================

def main():
    global official_count
    global general_count
    global reject_count
    global processed_urls
    global rejected_urls
    global TARGET_TOTAL_COUNT

    ap = argparse.ArgumentParser(
        description="만개의레시피 크롤러 → CSV(resume/dedup 참고) + Kafka recipe.crawl.raw"
    )
    ap.add_argument(
        "--kafka",
        action="store_true",
        help="검증 레시피를 recipe.crawl.raw 로 직접 produce (주기 크롤→컨슈머→PG 경로)"
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="이번 목표 전체 레시피 수 (테스트용, TARGET_TOTAL_COUNT override)"
    )
    args = ap.parse_args()

    if args.limit:
        TARGET_TOTAL_COUNT = args.limit
    if args.kafka:
        init_kafka()

    official_urls = load_existing_urls(
        OFFICIAL_FILE
    )
    general_urls = load_existing_urls(
        GENERAL_FILE
    )
    rejected_urls = load_existing_urls(
        REJECT_FILE
    )

    processed_urls = official_urls | general_urls

    official_count = len(official_urls)
    general_count = len(general_urls)
    reject_count = len(rejected_urls)

    state = load_state()
    start_page = state["last_completed_page"] + 1

    print("=" * 72)
    print("만개의레시피 추천순·재료분리 스트리밍 크롤러")
    print("=" * 72)
    print("정렬 방식: 추천순(order=reco)")
    print(f"시작 페이지: {start_page}")
    print(f"기존 공식 레시피: {official_count}")
    print(f"기존 일반 레시피: {general_count}")
    print(f"기존 제외 레시피: {reject_count}")
    print(f"목표 전체 레시피: {TARGET_TOTAL_COUNT}")

    if (
        official_count + general_count
        >= TARGET_TOTAL_COUNT
    ):
        print("이미 목표 수량을 달성했습니다.")
        return

    consecutive_empty_pages = 0

    try:
        for page_num in range(
            start_page,
            MAX_LIST_PAGES + 1
        ):
            if (
                official_count + general_count
                >= TARGET_TOTAL_COUNT
            ):
                print("\n목표 수량에 도달했습니다.")
                break

            link_count = process_page(page_num)

            if link_count == 0:
                consecutive_empty_pages += 1

                print(
                    f"페이지 {page_num}: "
                    f"목록 없음 "
                    f"({consecutive_empty_pages}회 연속)"
                )

                if consecutive_empty_pages >= 3:
                    print(
                        "목록이 3페이지 연속 비어 있어 "
                        "작업을 종료합니다."
                    )
                    break
            else:
                consecutive_empty_pages = 0

            save_state(page_num)

            print(
                f"페이지 {page_num} 완료 | "
                f"공식 {official_count}, "
                f"일반 {general_count}, "
                f"제외 {reject_count}, "
                f"전체 {official_count + general_count}"
            )

    except KeyboardInterrupt:
        print("\n사용자 중단 요청을 감지했습니다.")
        print(
            "현재 페이지 이전까지의 데이터는 "
            "CSV와 상태 파일에 저장되어 있습니다."
        )

    finally:
        print("\n" + "=" * 72)
        print("작업 종료")
        print("=" * 72)
        print(f"공식 레시피: {official_count}")
        print(f"일반 레시피: {general_count}")
        print(f"제외 레시피: {reject_count}")
        print(
            f"전체 검증 레시피: "
            f"{official_count + general_count}"
        )
        print(
            f"공식 파일: "
            f"{os.path.abspath(OFFICIAL_FILE)}"
        )
        print(
            f"일반 파일: "
            f"{os.path.abspath(GENERAL_FILE)}"
        )
        print(
            f"재료 파일: "
            f"{os.path.abspath(INGREDIENT_FILE)}"
        )
        print(
            f"제외 파일: "
            f"{os.path.abspath(REJECT_FILE)}"
        )
        print(
            f"상태 파일: "
            f"{os.path.abspath(STATE_FILE)}"
        )

        if _producer is not None:
            _producer.flush()
            print(f"Kafka produce: {kafka_produced} → recipe.crawl.raw")
        print(f"FB_POLLER_RECORDS {kafka_produced}")


if __name__ == "__main__":
    main()
