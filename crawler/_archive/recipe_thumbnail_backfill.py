import csv
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_URL = "https://www.10000recipe.com"

INPUT_FILES = [
    "공식_레시피.csv",
    "일반_검증완료_레시피.csv",
]

OUTPUT_FILE = "레시피_썸네일.csv"
FAIL_FILE = "썸네일_추출실패.csv"

MAX_WORKERS = 3
REQUEST_TIMEOUT = 15
REQUEST_DELAY_MIN = 0.5
REQUEST_DELAY_MAX = 1.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}

OUTPUT_COLUMNS = ["레시피ID", "썸네일URL"]
FAIL_COLUMNS = ["레시피ID", "레시피URL", "실패사유"]

csv_lock = threading.Lock()
request_lock = threading.Lock()
thread_local = threading.local()


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_recipe_url(recipe_id, recipe_url):
    recipe_url = clean_text(recipe_url)
    recipe_id = clean_text(recipe_id)

    if recipe_url:
        return recipe_url

    if recipe_id:
        return f"{BASE_URL}/recipe/{recipe_id}"

    return ""


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


def extract_thumbnail_url(soup):
    meta_selectors = [
        "meta[property='og:image']",
        "meta[name='twitter:image']",
        "meta[property='twitter:image']",
    ]

    for selector in meta_selectors:
        node = soup.select_one(selector)

        if not node:
            continue

        image_url = clean_text(node.get("content"))

        if image_url:
            return urljoin(BASE_URL, image_url)

    image_selectors = [
        ".centeredcrop img",
        ".view2_pic img",
        ".view2_summary img",
        ".common_sp_thumb img",
    ]

    for selector in image_selectors:
        node = soup.select_one(selector)

        if not node:
            continue

        image_url = (
            node.get("src")
            or node.get("data-src")
            or node.get("data-original")
            or ""
        )

        image_url = clean_text(image_url)

        if image_url:
            return urljoin(BASE_URL, image_url)

    return ""


def append_csv_row(file_name, columns, row):
    file_exists = os.path.exists(file_name)

    with open(
        file_name,
        "a",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=columns,
            extrasaction="ignore",
        )

        if not file_exists:
            writer.writeheader()

        writer.writerow(row)
        file.flush()


def load_existing_ids(file_name):
    existing_ids = set()

    if not os.path.exists(file_name):
        return existing_ids

    with open(
        file_name,
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            recipe_id = clean_text(row.get("레시피ID"))

            if recipe_id:
                existing_ids.add(recipe_id)

    return existing_ids


def load_recipe_targets():
    targets_by_id = {}

    for file_name in INPUT_FILES:
        if not os.path.exists(file_name):
            print(f"[입력 파일 없음] {file_name}")
            continue

        with open(
            file_name,
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.DictReader(file)

            for row in reader:
                recipe_id = clean_text(row.get("레시피ID"))
                recipe_url = clean_text(row.get("레시피URL"))

                if not recipe_id:
                    continue

                if recipe_id not in targets_by_id:
                    targets_by_id[recipe_id] = {
                        "레시피ID": recipe_id,
                        "레시피URL": normalize_recipe_url(
                            recipe_id,
                            recipe_url,
                        ),
                    }

    return list(targets_by_id.values())


def fetch_thumbnail(target):
    recipe_id = target["레시피ID"]
    recipe_url = target["레시피URL"]

    if not recipe_url:
        return {
            "success": False,
            "레시피ID": recipe_id,
            "레시피URL": "",
            "실패사유": "RECIPE_URL_MISSING",
        }

    try:
        response = request_page(recipe_url)
        soup = BeautifulSoup(response.text, "html.parser")

        thumbnail_url = extract_thumbnail_url(soup)

        if not thumbnail_url:
            return {
                "success": False,
                "레시피ID": recipe_id,
                "레시피URL": recipe_url,
                "실패사유": "THUMBNAIL_NOT_FOUND",
            }

        return {
            "success": True,
            "레시피ID": recipe_id,
            "썸네일URL": thumbnail_url,
        }

    except requests.HTTPError as error:
        status_code = (
            error.response.status_code
            if error.response is not None
            else "UNKNOWN"
        )

        return {
            "success": False,
            "레시피ID": recipe_id,
            "레시피URL": recipe_url,
            "실패사유": f"HTTP_ERROR_{status_code}",
        }

    except requests.RequestException:
        return {
            "success": False,
            "레시피ID": recipe_id,
            "레시피URL": recipe_url,
            "실패사유": "REQUEST_ERROR",
        }

    except Exception as error:
        return {
            "success": False,
            "레시피ID": recipe_id,
            "레시피URL": recipe_url,
            "실패사유": f"PARSING_ERROR: {error}",
        }


def main():
    targets = load_recipe_targets()

    if not targets:
        print("수집할 레시피가 없습니다.")
        print(
            "공식_레시피.csv 또는 일반_검증완료_레시피.csv가 "
            "현재 폴더에 있는지 확인하세요."
        )
        return

    completed_ids = load_existing_ids(OUTPUT_FILE)
    failed_ids = load_existing_ids(FAIL_FILE)

    pending_targets = [
        target
        for target in targets
        if target["레시피ID"] not in completed_ids
        and target["레시피ID"] not in failed_ids
    ]

    print("=" * 70)
    print("레시피 썸네일 URL 백필 크롤러")
    print("=" * 70)
    print(f"전체 레시피: {len(targets)}개")
    print(f"기존 완료: {len(completed_ids)}개")
    print(f"기존 실패: {len(failed_ids)}개")
    print(f"이번 실행 대상: {len(pending_targets)}개")
    print(f"출력 파일: {OUTPUT_FILE}")

    success_count = 0
    fail_count = 0

    try:
        with ThreadPoolExecutor(
            max_workers=MAX_WORKERS
        ) as executor:

            future_map = {
                executor.submit(
                    fetch_thumbnail,
                    target,
                ): target
                for target in pending_targets
            }

            for index, future in enumerate(
                as_completed(future_map),
                start=1,
            ):
                result = future.result()

                with csv_lock:
                    if result["success"]:
                        append_csv_row(
                            OUTPUT_FILE,
                            OUTPUT_COLUMNS,
                            {
                                "레시피ID": result["레시피ID"],
                                "썸네일URL": result["썸네일URL"],
                            },
                        )
                        success_count += 1
                    else:
                        append_csv_row(
                            FAIL_FILE,
                            FAIL_COLUMNS,
                            {
                                "레시피ID": result["레시피ID"],
                                "레시피URL": result["레시피URL"],
                                "실패사유": result["실패사유"],
                            },
                        )
                        fail_count += 1

                if index % 10 == 0 or index == len(pending_targets):
                    print(
                        f"[{index}/{len(pending_targets)}] "
                        f"성공 {success_count}, 실패 {fail_count}"
                    )

    except KeyboardInterrupt:
        print("\n사용자 중단 요청을 감지했습니다.")
        print(
            "이미 처리된 결과는 CSV에 저장되어 있으며, "
            "재실행하면 이어서 진행됩니다."
        )

    finally:
        print("\n" + "=" * 70)
        print("작업 종료")
        print("=" * 70)
        print(f"이번 실행 성공: {success_count}")
        print(f"이번 실행 실패: {fail_count}")
        print(f"결과 파일: {os.path.abspath(OUTPUT_FILE)}")
        print(f"실패 파일: {os.path.abspath(FAIL_FILE)}")


if __name__ == "__main__":
    main()
