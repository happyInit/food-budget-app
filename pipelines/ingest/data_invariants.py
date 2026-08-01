"""데이터 불변식 점검 — **다음 결함을 손이 아니라 배치가 찾게 한다**.

## 왜 만들었나

2026-07-30 에 **유저에게 보이던 결함 4건**을 고쳤는데, 넷 다 **손으로 훑다가** 발견했다:

  1. `realign_prices` 가 `is_food` 를 되돌리지 않아 식비에서 품목이 조용히 증발
  2. FK 위반으로 fan-out 컨슈머가 무한 크래시 루프에 빠질 수 있었음
  3. CRF 색상어(`빨간색`)가 재료로 화면에 표시
  4. RAW 빈 이름 행이 1,143 레시피에서 빈 재료 줄로 표시

유형별로 전수 조사한 결과 **세 유형 모두 거의 소진**됐다(A 보정후 파생값 0건 추가 ·
B FK크래시 0건 추가 · C 비데이터노출 8행). 즉 지금 남은 문제는 **"더 있느냐"가 아니라
"다음 것을 어떻게 발견하느냐"** 다.

`docs/prd/migrations/2026-07-29_preflight.sql` 이 비슷한 개념이지만 **DDL 적용 전 1회용**이고,
클러스터에 주기적 점검이 없다(실측: `pipeline` ns CronJob 11개 중 품질 점검 0개).

    python pipelines/ingest/data_invariants.py           # 전체 점검
    python pipelines/ingest/data_invariants.py --quiet   # 위반만 출력(크론용)
    종료: 0=통과 · 1=하드 불변식 위반 · 2=DB 접속 실패

## 🔴 하드/소프트를 나눈 이유 — 헛경보가 장치를 죽인다

후보를 운영 데이터로 먼저 재보니 **두 개는 불변식이 아니었다**:

  · `expire_at < created_at` (11건) — `_PATCH_COLS` 에 `expire_at` 이 있어 **유저가 직접 수정**할
    수 있다. 포장 표기의 지난 날짜를 입력하는 것은 정당하다. → 실패로 두면 매주 헛경보.
  · `(item_id, storage)` 중복 source (3건) — 전부 `item_id IS NULL` 이고 `lookup_shelf_life` 는
    `item_id` 로 조인하므로 **조회에 영향이 없다**. → 범위를 좁혀야 불변식이 된다.

가짜 실패가 섞이면 사람은 경보를 무시하기 시작하고 **진짜가 가려진다**(mp-chat-insights 가
정상 스킵에 exit 2 를 써서 매일 Error 파드를 만들던 것과 같은 실패 유형이다).
그래서 **하드는 반드시 0인 것만** 넣고, 추세로 봐야 할 것은 **소프트**로 분리했다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _db import connect  # noqa: E402

# ── 하드 불변식 — 위반하면 결함이다. 전부 **현재 0 임을 운영 PG 로 확인**했다. ──────
# (name, sql, 위반이 뜻하는 것)
HARD = [
    ("색상어 단독 재료행",
     r"""SELECT count(*) FROM recipe_ingredient
          WHERE ingredient_name ~ '^(빨간|노란|파란|초록|검은|하얀|보라|주황|분홍|갈|자|적|청|황|녹|백|흑|회|남)색$'""",
     "CRF 가 색상 수식어를 재료로 뽑았다 — 유저 화면에 재료로 보인다(backfill 의 _COLOR_ONLY 필터 확인)"),

    ("소비기한 min > max",
     "SELECT count(*) FROM shelf_life_ref "
     "WHERE days_min IS NOT NULL AND days_max IS NOT NULL AND days_min > days_max",
     "기한 하한이 상한보다 크다 — estimate_expire_date 가 max 를 우선하므로 더 짧은 날짜가 나온다"),

    # ⚠️ item_id IS NOT NULL 로 좁힌다 — NULL 행은 lookup_shelf_life 가 조인으로 걸러 조회에 영향이 없다.
    ("(item,storage) 조합에 같은 source 중복",
     """SELECT count(*) FROM (
          SELECT item_id, storage FROM shelf_life_ref WHERE item_id IS NOT NULL
           GROUP BY 1,2 HAVING count(*) <> count(DISTINCT source)) x""",
     "lookup_shelf_life 가 같은 우선순위 행 중 무엇을 고를지 비결정적이 된다"),

    ("요약 review_count 와 실제 분류수 불일치",
     """SELECT count(*) FROM recipe_review_summary s
         WHERE s.review_count <> (SELECT count(*) FROM recipe_review r
                                    JOIN recipe_review_sentiment t ON t.review_id = r.id
                                   WHERE r.recipe_id = s.recipe_id)""",
     "유저에게 보이는 '후기 N건 중 x%' 의 N 이 실제와 다르다"),

    ("price_alert_sent 고아 행",
     """SELECT count(*) FROM price_alert_sent a
         WHERE NOT EXISTS (SELECT 1 FROM price_anomaly p WHERE p.id = a.anomaly_id)""",
     "발송 이력이 근거를 잃었다 — '왜 이 알림이 갔나'에 답할 수 없다"),

    ("요약이 있는데 리뷰가 0건",
     """SELECT count(*) FROM recipe_review_summary s
         WHERE NOT EXISTS (SELECT 1 FROM recipe_review r WHERE r.recipe_id = s.recipe_id)""",
     "근거 없는 요약이 유저에게 표시된다 — 리뷰가 지워졌거나 집계가 어긋난 것"),
]

# ── 소프트 신호 — 0 이 아닌 것이 정상일 수 있다. **추세**로 본다(실패시키지 않는다). ──
SOFT = [
    ("재고 만료일 < 등록일",
     """SELECT count(*) FROM pantry.pantry_item
         WHERE expire_at IS NOT NULL AND expire_at < created_at::date""",
     "유저가 포장 표기의 지난 날짜를 직접 입력했을 수 있다(_PATCH_COLS 에 expire_at 있음). 급증하면 조사"),

    ("AI_DRAFT 가 유효 조회값인 조합",
     """SELECT count(*) FROM shelf_life_ref a
         WHERE a.source = 'AI_DRAFT'
           AND NOT EXISTS (SELECT 1 FROM shelf_life_ref b
                            WHERE b.item_id = a.item_id AND b.storage = a.storage
                              AND b.source IN ('CURATED','FOODKEEPER'))""",
     "미검수 초안이 실제 조회에 쓰이는 수 — 검수 진행에 따라 줄어야 한다(식품안전)"),

    ("NER 미매칭 재료행",
     "SELECT count(*) FROM recipe_ingredient WHERE ner_status='NER_PARSED' AND item_id IS NULL",
     "gazetteer 커버리지 — #130 정책 확정 후 줄어야 한다"),

    ("감정 미분류 리뷰",
     """SELECT count(*) FROM recipe_review r
         LEFT JOIN recipe_review_sentiment s ON s.review_id = r.id
         WHERE s.review_id IS NULL""",
     "분류 배치가 못 잡은 건 — temperature=0 이라 재실행으로 안 낫는다(백로그 §1.1)"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="데이터 불변식 점검(읽기 전용)")
    ap.add_argument("--quiet", action="store_true", help="위반만 출력(크론용)")
    args = ap.parse_args()

    try:
        conn = connect()
    except Exception as exc:  # noqa: BLE001 — 접속 실패는 결함과 구분한다(종료코드 2)
        print(f"⚠️  DB 접속 실패(점검 불가): {exc}")
        return 2

    violations = []
    with conn:
        if not args.quiet:
            print("── 하드 불변식(위반 = 결함) ──")
        for name, sql, meaning in HARD:
            n = conn.execute(sql).fetchone()[0]
            if n:
                violations.append((name, n, meaning))
                print(f"  🔴 {name}: {n:,}건")
                print(f"     → {meaning}")
            elif not args.quiet:
                print(f"  ✅ {name}: 0")

        if not args.quiet:
            print("\n── 소프트 신호(추세로 본다 · 실패 아님) ──")
            for name, sql, meaning in SOFT:
                n = conn.execute(sql).fetchone()[0]
                print(f"  {n:>7,}  {name}")
                print(f"           {meaning}")

    if violations:
        print(f"\n🔴 하드 불변식 {len(violations)}건 위반 — 결함이다. 원인을 찾을 것.")
        return 1
    if not args.quiet:
        print("\n✅ 하드 불변식 전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
