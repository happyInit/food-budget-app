"""'구매' 재료명 파싱버그 백필 — 영향받은 레시피만 재크롤 → Kafka 재발행.

**왜 필요한가.** `extract_ingredients()`가 재료명을 `item.select_one("a")`(첫 <a>)로 뽑았는데,
만개는 **재료 정보 페이지가 있는 재료만** 이름을 `<a href="javascript:viewMaterial(...)">`로
감싼다. 없는 재료(예: 통팥조림)는 이름이 평문이라 첫 <a>가 구매 버튼
(`<a class="ingre_list_btn" href="javascript:buyCpMaterial(...)">구매</a>`)이 되어
**재료명이 '구매'로 덮였다** — 실측 2026-07-21 기준 446 레시피 / 510행.
파서는 고쳤지만(`.ingre_list_name` 사용), 크롤러는 이미 처리한 URL을 재수집하지 않으므로
(CSV `processed_urls` dedup) 기존 446건은 이 백필로만 복구된다.

하필 **흔치 않은 재료일수록 링크가 없어** 유실됐다 — 큐레이션이 가장 필요한 재료들이다.

재크롤 결과는 크롤러와 동일하게 `recipe.crawl.raw`로 발행하고, 나머지(upsert·재료 재삽입·
gazetteer 매칭)는 기존 컨슈머가 처리한다. 컨슈머가 `(source, src_recipe_id)` upsert +
재료 delete→insert 이므로 **여러 번 돌려도 안전(멱등)**.

사용:
  python crawler/10k_recipe/reparse_buy_link_backfill.py --dry-run   # 대상만 출력
  python crawler/10k_recipe/reparse_buy_link_backfill.py --kafka     # 실제 재발행
  python crawler/10k_recipe/reparse_buy_link_backfill.py --kafka --limit 20
"""
import argparse
import importlib.util
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[2] / "pipelines/ingest"))

# 크롤러 모듈명이 숫자로 시작(10k_recipe_crawler)해 일반 import 불가 → 파일 경로 로드.
_spec = importlib.util.spec_from_file_location(
    "k10_crawler", _HERE.parent / "10k_recipe_crawler.py"
)
crawler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crawler)

TARGET_SQL = """
select distinct r.src_recipe_id
  from recipe r
  join recipe_ingredient ri on ri.recipe_id = r.id
 where r.source = '10K'
   and ri.ingredient_name = '구매'
 order by r.src_recipe_id
"""


def targets(limit=None):
    from _db import connect  # noqa: E402 — pipelines/ingest/_db.py

    with connect() as conn, conn.cursor() as cur:
        cur.execute(TARGET_SQL)
        ids = [row[0] for row in cur.fetchall()]
    return ids[:limit] if limit else ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kafka", action="store_true", help="recipe.crawl.raw 로 재발행")
    ap.add_argument("--dry-run", action="store_true", help="대상만 출력하고 종료")
    ap.add_argument("--limit", type=int, help="상위 N건만 처리(시범 실행용)")
    args = ap.parse_args()

    ids = targets(args.limit)
    print(f"대상 레시피: {len(ids)}건")
    if args.dry_run or not ids:
        for src in ids[:20]:
            print(f"  https://www.10000recipe.com/recipe/{src}")
        if len(ids) > 20:
            print(f"  … 외 {len(ids) - 20}건")
        return 0

    if args.kafka:
        crawler.init_kafka()

    ok = failed = still_bad = 0
    for i, src in enumerate(ids, 1):
        url = f"{crawler.BASE_URL}/recipe/{src}"
        result = crawler.crawl_recipe_detail(url)
        if not result.get("valid"):
            failed += 1
            print(f"  [{i}/{len(ids)}] {src} 실패: {result.get('reason')}")
            continue

        names = [g["name"] for g in result["ingredients"]]
        if "구매" in names:
            # 파서 수정이 안 먹은 레이아웃 → 발행하지 않고 보고(조용한 회귀 방지)
            still_bad += 1
            print(f"  [{i}/{len(ids)}] {src} ⚠️ 여전히 '구매' 포함 — 스킵")
            continue

        if args.kafka:
            crawler.produce_record(result["data"], result["ingredients"], result["steps"])
        ok += 1
        if i % 50 == 0:
            print(f"  [{i}/{len(ids)}] 진행 중 (성공 {ok} · 실패 {failed} · 잔존 {still_bad})")

    # 🔴 종전엔 `flush(30)` 반환값을 버렸다. 그마저도 큐 잔량만 세므로 만료 실패는 못 본다(#558).
    delivery = None
    if args.kafka and crawler._producer is not None:
        delivery = crawler.finalize_kafka()

    print(f"\n완료: 재발행 {ok} · 실패 {failed} · '구매' 잔존 {still_bad}"
          + (f" · {delivery.summary()}" if delivery else ""))
    if still_bad:
        print("⚠️ 잔존분은 파서가 못 잡은 레이아웃 — 별도 확인 필요")
    # 전달 확인된 수만 관측 지표로 내보낸다 — ok 는 "발행 시도" 수였다.
    print(f"FB_POLLER_RECORDS {delivery.delivered if delivery else ok}")
    if delivery is not None and not delivery.ok:
        print("🔴 전달이 확인되지 않았다 — 성공으로 마감하지 않는다.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
