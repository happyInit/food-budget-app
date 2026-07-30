"""retail_product.volume_ml 백필 — 상품명에서 부피를 파싱해 컬럼에 채운다 (#286).

    python pipelines/ingest/backfill_volume_ml.py              # 미리보기(기본)
    python pipelines/ingest/backfill_volume_ml.py --apply

## 왜 필요한가

`volume_ml` 은 컬럼이 있는데 **한 번도 채워진 적이 없다(0%)**. 그래서 `retail_unit_price`
뷰가 조회 때마다 **상품명을 SQL 정규식으로** 파싱해 부피 단가를 냈고, 그 구조가
2026-07-23 장애를 만들었다 — `"솔리몬 스퀴즈드 레몬즙 1,000ml"` 에서 콤마를 못 읽어
`000` 을 잡고 0 으로 나눠 **뷰 REFRESH 가 통째로 죽었다.** 4,634행 중 1행이 가격 갱신
전체를 멈춰 세웠다.

파이프라인(`load_retail.refine_record`)은 이제 쓰기 시점에 채운다. 이 스크립트는
**이미 쌓인 행**을 재크롤 없이 따라잡게 한다.

## 안전 규칙

- **모르면 건드리지 않는다.** 파서가 None 을 주면 그 행은 UPDATE 대상이 아니다.
  NULL 은 "이 상품만 부피 단가 없음"이지만, 틀린 숫자는 조용히 잘못된 가격을 판다.
- **이미 값이 있으면 덮지 않는다** (`volume_ml IS NULL` 조건). 크롤러가 실어 보낸
  진짜 값을 이름 파싱 결과로 밀어내면 안 된다.
- 기본이 미리보기다. `--apply` 없이는 아무것도 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _db import connect                    # noqa: E402
from retail_norm import parse_volume_ml    # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="retail_product.volume_ml 백필(기본: 미리보기)")
    ap.add_argument("--apply", action="store_true", help="실제로 UPDATE (기본: 미리보기)")
    ap.add_argument("--limit", type=int, help="상위 N건만")
    args = ap.parse_args()

    conn = connect()
    cur = conn.cursor()

    # volume_ml 이 비어 있는 행만 읽는다 — 크롤러가 준 값을 덮지 않기 위해서다.
    cur.execute("select id, source, name from retail_product where volume_ml is null")
    rows = cur.fetchall()

    hits = []
    for rid, source, name in rows:
        v = parse_volume_ml(name or "")
        if v is not None:
            hits.append((rid, source, name, v))
    if args.limit:
        hits = hits[: args.limit]

    print(f"volume_ml 비어 있음 {len(rows):,}행  →  파싱 성공 {len(hits):,}행 "
          f"({'적용' if args.apply else '미리보기'})\n")
    by_source: dict[str, int] = {}
    for _, s, _, _ in hits:
        by_source[s] = by_source.get(s, 0) + 1
    for s, c in sorted(by_source.items()):
        print(f"  {s}: {c:,}")

    print("\n표본 15건:")
    for rid, s, name, v in hits[:15]:
        print(f"  {v:>7,} ml  {(name or '')[:60]}")

    if not args.apply:
        print(f"\n→ 미리보기(무변경). 적용하려면 --apply")
        cur.close(); conn.close()
        return 0

    for rid, _, _, v in hits:
        # 조건을 UPDATE 문에도 다시 건다 — 읽은 뒤 크롤러가 값을 채웠을 수 있다(경합 방지).
        cur.execute("update retail_product set volume_ml=%s where id=%s and volume_ml is null",
                    (v, rid))
    conn.commit()

    cur.execute("select count(*) filter (where volume_ml is not null), count(*) from retail_product")
    filled, total = cur.fetchone()
    print(f"\n→ 적용 완료. volume_ml 채움 {filled:,}/{total:,} ({filled / total * 100:.1f}%)")
    cur.close(); conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
