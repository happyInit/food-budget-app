"""재고 소비기한 재계산 — 참조표가 나중에 채워진 건을 따라잡는다 (백로그 §1.9).

**무엇을 고치나.** `pantry_item.expire_at` 은 **등록 시점에 한 번만** 계산된다
(`services/pantry` 가 `estimate_expire_date(담은날, days_min, days_max)` 로 계산해 저장).
그래서 등록 당시 `shelf_life_ref` 에 그 `(item_id, storage)` 조합이 없었다면 `expire_at` 은
NULL 로 남고, **나중에 참조표를 채워도 영영 NULL 이다.**

AI 초안 검수 승격·큐레이션 추가는 계속 일어나므로 그때마다 그 사이 등록분이 또 NULL 로 쌓인다.
`2026-07-29g` 마이그레이션이 12건을 소급했으나 **그건 일회성 패치이지 구조가 아니었다.**
이 스크립트가 그 자리를 메운다 — 주기 실행으로 참조표 갱신을 자동으로 따라잡는다.

    python pipelines/ingest/recompute_pantry_expire.py            # 미리보기(무변경)
    python pipelines/ingest/recompute_pantry_expire.py --apply    # 실제 반영

── 🔴 왜 "미래가 되는 것만" 채우는가 ────────────────────────────────────────────
실측(2026-07-30): 채울 수 있는 2건이 **전부 이미 지난 날짜**가 된다.
그대로 넣으면 "기한 없음"으로 보이던 재고가 갑자기 "지남"으로 바뀌고, 임박 목록
(`expire_at <= current_date + 7` — **과거 날짜도 잡는다**)에 들어가 26 → 28 이 된다.

정보로는 정확하지만 **행동 가능성이 없다.** 몇 주 전 담은 재료는 이미 먹었거나 버렸을 가능성이
높고, 지금 와서 "지났다"고 알리는 건 알림만 늘려 **알림 자체의 신뢰를 깎는다**(마른김 사례와
같은 실패 유형이다).

그리고 팀 결정이 *"기한을 모르면 표시하지 않고 포장 표기를 안내"* 다 — **NULL 은 "모름"이라는
정직한 상태**이지 결손이 아니다. 그래서 과거가 되는 건 **일부러 NULL 로 남긴다.**

── 안전 규칙 3가지 ─────────────────────────────────────────────────────────────
1. **`expire_at IS NULL` 만 건드린다.** 이미 값이 있는 행은 유저가 본 날짜다 — 바꾸지 않는다
   (유저 입력일 수도 있다).
2. **결과가 미래인 것만.** 위 사유.
3. **멱등.** 다시 돌려도 대상이 없으면 무동작. 배치가 겹쳐도 안전하다.

`2026-07-29g` 와 달리 로그 테이블을 쓰지 않는다 — 되돌리기가 `expire_at = NULL` 한 줄이고,
어떤 행이 바뀌었는지는 이 스크립트가 출력으로 남긴다(주기 실행이라 로그 테이블은 계속 커진다).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _db import connect  # noqa: E402

# 대상 선정 — `lookup_shelf_life` 와 **같은 조건**으로 찾는다.
#   · 조인 키는 반드시 **(item_id, storage) 조합**이다. item_id 만 보면 "ROOM 만 있는 감자"가
#     커버됨으로 잡혀 FRIDGE 재고가 영영 안 채워진다(2026-07-29 실측 사고).
#   · 소스 우선순위 CURATED > FOODKEEPER > AI_DRAFT — 검수본이 초안에 덮이지 않게.
#   · 정책은 `estimate_expire_date` 와 동일: days_max 우선, 없으면 days_min.
_TARGETS = """
SELECT p.id,
       p.name,
       p.storage,
       (p.created_at::date + COALESCE(s.days_max, s.days_min)) AS new_expire,
       s.source
  FROM pantry.pantry_item p
  JOIN LATERAL (
        SELECT x.source, x.days_min, x.days_max
          FROM public.shelf_life_ref x
         WHERE x.item_id = p.item_id AND x.storage = p.storage
         ORDER BY CASE x.source WHEN 'CURATED' THEN 0
                                WHEN 'FOODKEEPER' THEN 1 ELSE 2 END
         LIMIT 1
       ) s ON TRUE
 WHERE p.status = 'ACTIVE'
   AND p.expire_at IS NULL                                   -- 안전규칙 1
   AND COALESCE(s.days_max, s.days_min) IS NOT NULL
   AND (p.created_at::date + COALESCE(s.days_max, s.days_min)) > CURRENT_DATE   -- 안전규칙 2
 ORDER BY p.id
"""

# 조건을 UPDATE 에도 다시 건다 — 조회와 갱신 사이에 유저가 값을 넣었을 수 있다(경쟁 방어).
_UPDATE = """
UPDATE pantry.pantry_item
   SET expire_at = %(new_expire)s
 WHERE id = %(id)s AND expire_at IS NULL
"""

# 참고 지표 — 채우지 못한 이유를 나눠 보여준다(무엇이 남았는지 알아야 다음 조치가 정해진다).
_LEFTOVER = """
SELECT
  count(*) FILTER (WHERE ref.days IS NULL)                                   AS no_reference,
  count(*) FILTER (WHERE ref.days IS NOT NULL
                     AND (p.created_at::date + ref.days) <= CURRENT_DATE)    AS would_be_past
  FROM pantry.pantry_item p
  LEFT JOIN LATERAL (
        SELECT COALESCE(x.days_max, x.days_min) AS days
          FROM public.shelf_life_ref x
         WHERE x.item_id = p.item_id AND x.storage = p.storage
         ORDER BY CASE x.source WHEN 'CURATED' THEN 0
                                WHEN 'FOODKEEPER' THEN 1 ELSE 2 END
         LIMIT 1
       ) ref ON TRUE
 WHERE p.status = 'ACTIVE' AND p.expire_at IS NULL
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="재고 소비기한 재계산(참조표 갱신 따라잡기)")
    ap.add_argument("--apply", action="store_true",
                    help="실제로 UPDATE(기본: 미리보기만). 유저 노출 값이라 명시적 플래그를 요구한다")
    ap.add_argument("--limit", type=int, help="상위 N건만(시범)")
    args = ap.parse_args()

    with connect() as conn:
        rows = conn.execute(_TARGETS).fetchall()
        if args.limit:
            rows = rows[: args.limit]

        print(f"재계산 대상 {len(rows):,}건 (expire_at IS NULL · 참조표 존재 · 결과가 미래)")
        for r in rows[:30]:
            print(f"  #{r[0]:<6} {str(r[1])[:18]:<20} {r[2]:<8} → {r[3]}  ({r[4]})")
        if len(rows) > 30:
            print(f"  … 외 {len(rows) - 30:,}건")

        if not args.apply:
            no_ref, past = conn.execute(_LEFTOVER).fetchone()
            print(f"\n남는 NULL: 참조표 없음 {no_ref:,}건 · 과거가 되어 제외 {past:,}건")
            print("  ↑ '과거가 되어 제외'는 **의도된 것**이다 — 행동 가능성이 없는 알림을 만들지 않는다")
            print("\n→ 미리보기(무변경). 적용하려면 --apply")
            return

        updated = 0
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(_UPDATE, {"id": r[0], "new_expire": r[3]})
                updated += cur.rowcount
        conn.commit()

        no_ref, past = conn.execute(_LEFTOVER).fetchone()
        print(f"\n갱신 {updated:,}건 (대상 {len(rows):,} 중 — 차이는 그사이 유저가 값을 넣은 행)")
        print(f"남는 NULL: 참조표 없음 {no_ref:,}건 · 과거가 되어 제외 {past:,}건")
        print("\n되돌리기: UPDATE pantry.pantry_item SET expire_at = NULL WHERE id IN (…);")


if __name__ == "__main__":
    main()
