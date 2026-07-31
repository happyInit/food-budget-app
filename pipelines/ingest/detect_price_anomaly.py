"""최저가 이상탐지 배치 — 품목×소스 단가 시계열의 z-score 급락 감지 (`ai-spec.md §2`).

라벨 없는 **자체 통계**라 콜드스타트에 강하다(서비스 첫날부터 동작). 외부 API 비용 0.

입력  : `retail_price`(크롤 스냅샷 시계열) × `retail_product`(item_id·weight_g)
단위  : **100g 단가**로 정규화 — 원시 `price`는 팩 크기 아티팩트라 비교 불가(`retail_unit_price` 뷰와 같은 근거)
판정  : 품목×소스별 baseline(직전 이력) 대비 `z = (현재 - μ) / σ`
출력  : 이상 목록(JSON) — 발행(Kafka LOW_PRICE)·fan-out은 별도 단계

실측 캘리브레이션(2026-07-28, 14일치 71,727행):
  · 표본 N>=7 시계열 488개 · z 분포 p5=-2.45 / p10=-1.42 / 중앙 +0.37
  · z<=-2.0 → 15건(7.1%) · z<=-2.5 → 9건(4.2%) · z<=-3.0 → 8건(3.8%)
  ⚠️ **z만으로는 부족**: item=95는 z=-16.95인데 실제 하락은 -7%뿐이었다(σ=7원으로 극소).
     "원래 안 움직이던 품목이 조금 움직인 것"이 최상위로 올라와 체감 없는 알림이 된다.
     → **z + 최소 하락률(MIN_DROP_PCT) 동시 충족**을 요구한다.

⚠️ baseline 한계: 현재 이력이 14일치라 `ai-spec §2`의 30일 이동평균에 못 미친다.
   스펙도 "4주 미만 구간은 오탐↑"을 경고하므로, 고정 30일 대신 **적응형 윈도우**
   (가용 이력 최대 WINDOW_DAYS, 최소 MIN_SAMPLES 미달은 스킵)를 쓰고 표본 수를 결과에 실어
   신뢰도를 노출한다. 이력이 쌓이면 파라미터만 조여도 그대로 동작한다.

사용:
  python pipelines/ingest/detect_price_anomaly.py              # 요약 출력
  python pipelines/ingest/detect_price_anomaly.py --json out.json
  python pipelines/ingest/detect_price_anomaly.py --z -2.5 --min-drop 12
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from _db import connect

WINDOW_DAYS = 30      # baseline 상한(가용 이력이 적으면 있는 만큼). ai-spec §2 = 30일 이동평균
MIN_SAMPLES = 7       # baseline 최소 일자 수. 실측상 N>=7이면 488개 시계열 확보
Z_THRESHOLD = -2.0    # 급락 판정 z. 실측 p5=-2.45라 -2.0은 하위 ~7%
MIN_DROP_PCT = 8.0    # 최소 하락률(%). σ가 극소한 품목의 "체감 없는 급락" 배제
TOP_N = 20            # 배치 채택 상한(팀 결정 2026-07-28) — 아래 "노출 정책" 참조

# ── 노출 정책 (팀 결정 2026-07-28) ────────────────────────────────────────────
#  조건 충족 품목이 많아질 때 무엇을 어떻게 보여줄지.
#  ① 배치 상한 TOP_N=20 — **체감(하락률) 순** 상위 20건만 채택.
#     현재 실측이 12건이라 평상시엔 걸리지 않는 **안전판**이다. 크롤 이상으로 가격이
#     잘못 들어오거나(폭주) 품목 수가 375 → 수천으로 늘 때 무한 증식을 막는다.
#     정렬을 z가 아니라 drop_pct로 하는 이유: 실측에서 z 상위가 체감 없는 품목이었다(σ 극소).
#  ② 유저당 일일 상한 — **미적용**. 알림은 유저가 **직접 관심 등록한 품목에만** 나가므로
#     원치 않는 알림이 구조적으로 발생하지 않는다. 인위적 상한은 오히려 "내가 등록한
#     품목이 싸졌는데 알림이 안 오는" 손실을 만든다.
#  ③ 재알림 쿨다운 7일 — 동일 (user, item, source)에 7일 내 재발송 금지.
#     급락이 며칠 지속되면 매일 같은 알림이 가는 것을 막는다.
#     ⚠️ ②·③은 유저 컨텍스트가 필요해 **fan-out 단계(C)**에서 구현한다. 이 배치는 ①만 책임진다.

_DAILY_SQL = """
WITH daily AS (
  SELECT rp.item_id,
         rp.source,
         p.crawled_at::date                      AS d,
         min(p.price / rp.weight_g * 100)        AS won_per_100g,
         min(p.discount_rate)                    AS discount_rate
  FROM retail_price p
  JOIN retail_product rp ON rp.id = p.retail_product_id
  WHERE rp.item_id IS NOT NULL
    AND rp.weight_g > 0
    AND p.price > 0
    AND p.is_sold_out IS NOT TRUE
    AND p.crawled_at >= now() - make_interval(days => %(window)s)
  GROUP BY 1, 2, 3
)
SELECT d.item_id, im.canonical_name, d.source, d.d, d.won_per_100g, d.discount_rate
FROM daily d
JOIN item_master im ON im.item_id = d.item_id
ORDER BY d.item_id, d.source, d.d
"""


@dataclass
class Anomaly:
    item_id: int
    canonical_name: str
    source: str
    observed_at: str          # 최신 관측일
    price_100g: float         # 현재 100g 단가
    baseline_mean: float
    baseline_std: float
    samples: int              # baseline 표본 일자 수 → 신뢰도 지표
    z_score: float
    drop_pct: float           # 평균 대비 하락률(양수 = 싸짐)
    is_record_low: bool       # 역대(윈도우 내) 최저 갱신
    discount_rate: int | None


def _series(rows) -> dict[tuple[int, str], dict]:
    """(item_id, source) → {name, points:[(date, 단가, 할인율)]}"""
    out: dict[tuple[int, str], dict] = {}
    for item_id, name, source, d, w100, disc in rows:
        e = out.setdefault((item_id, source), {"name": name, "points": []})
        e["points"].append((d, float(w100), disc))
    return out


def detect(rows, z_threshold=Z_THRESHOLD, min_drop_pct=MIN_DROP_PCT,
           min_samples=MIN_SAMPLES, top_n: int | None = TOP_N) -> list[Anomaly]:
    """시계열에서 급락을 찾는다. 순수 함수 — DB 없이 테스트 가능.

    반환은 **체감(하락률) 내림차순**이며 `top_n`으로 잘린다(노출 정책 ①).
    `top_n=None`이면 자르지 않는다(분석·튜닝용).
    """
    found: list[Anomaly] = []
    for (item_id, source), e in _series(rows).items():
        pts = e["points"]
        if len(pts) < min_samples + 1:      # baseline(최소 N) + 현재 1점
            continue
        *hist, cur = pts
        hist_vals = [w for _, w, _ in hist]
        cur_date, cur_price, cur_disc = cur

        mu = st.mean(hist_vals)
        sd = st.pstdev(hist_vals)
        if sd <= 0 or mu <= 0:              # 변동이 전혀 없으면 z가 정의되지 않음
            continue
        z = (cur_price - mu) / sd
        drop = (mu - cur_price) / mu * 100.0

        # z만 쓰면 σ가 극소한 품목이 체감 없이 최상위로 올라온다 → 하락률도 함께 요구.
        if z > z_threshold or drop < min_drop_pct:
            continue
        found.append(Anomaly(
            item_id=item_id, canonical_name=e["name"], source=source,
            observed_at=cur_date.isoformat() if isinstance(cur_date, date) else str(cur_date),
            price_100g=round(cur_price, 2),
            baseline_mean=round(mu, 2), baseline_std=round(sd, 2),
            samples=len(hist_vals), z_score=round(z, 2), drop_pct=round(drop, 1),
            is_record_low=cur_price <= min(hist_vals),
            discount_rate=int(cur_disc) if cur_disc is not None else None,
        ))
    found.sort(key=lambda a: a.drop_pct, reverse=True)   # 체감 큰 순(정책 ①)
    return found if top_n is None else found[:top_n]


def main() -> None:
    ap = argparse.ArgumentParser(description="최저가 이상탐지(z-score) 배치")
    ap.add_argument("--window", type=int, default=WINDOW_DAYS, help="baseline 상한 일수")
    ap.add_argument("--z", type=float, default=Z_THRESHOLD, help="급락 z 임계(음수)")
    ap.add_argument("--min-drop", type=float, default=MIN_DROP_PCT, help="최소 하락률 %%")
    ap.add_argument("--min-samples", type=int, default=MIN_SAMPLES, help="baseline 최소 표본")
    ap.add_argument("--top-n", type=int, default=TOP_N, help="채택 상한(0=무제한)")
    ap.add_argument("--json", help="결과 JSON 저장 경로")
    # 기본은 dry-run. 알림은 되돌릴 수 없어(유저에게 이미 나감) 명시적 --emit 없이는 발행하지 않는다.
    ap.add_argument("--emit", action="store_true",
                    help="탐지 결과를 Kafka price.anomaly.detected 로 발행(기본: 미발행)")
    args = ap.parse_args()

    with connect() as conn:
        rows = conn.execute(_DAILY_SQL, {"window": args.window}).fetchall()

    series_n = len(_series(rows))
    top_n = args.top_n or None
    matched = detect(rows, args.z, args.min_drop, args.min_samples, top_n=None)
    found = matched if top_n is None else matched[:top_n]

    print(f"시계열 {series_n}개 · 스캔 {len(rows):,}행 "
          f"(window={args.window}일 · z<={args.z} · drop>={args.min_drop}% · N>={args.min_samples})")
    capped = f" → 상위 {len(found)}건 채택(TOP_N={top_n})" if top_n and len(matched) > top_n else ""
    print(f"조건 충족 {len(matched)}건{capped}\n")
    for a in found:
        flag = " 🔻역대최저" if a.is_record_low else ""
        disc = f" · 할인 {a.discount_rate}%" if a.discount_rate else ""
        print(f"  [{a.source:6s}] {a.canonical_name}(item={a.item_id}) "
              f"{a.price_100g:,.0f}원/100g  ▼{a.drop_pct:.0f}% (평균 {a.baseline_mean:,.0f}) "
              f"z={a.z_score} N={a.samples}{flag}{disc}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump([asdict(a) for a in found], f, ensure_ascii=False, indent=1)
        print(f"\n→ {args.json}")

    if args.emit:
        # 발행은 여기까지만 — "누구에게 보낼지"는 fan-out 컨슈머가 price_watch를 보고 정한다.
        # 탐지 배치가 유저를 알 필요가 없어야 재실행·백필이 안전하다.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stream"))
        from produce_price_anomaly import emit_anomalies      # noqa: E402

        sent = emit_anomalies([asdict(a) for a in found])
        print(f"\n→ Kafka price.anomaly.detected 발행 {sent}건")


if __name__ == "__main__":
    main()
