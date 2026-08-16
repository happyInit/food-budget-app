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
# ai-spec §2 는 30일 이동평균, §4.1 은 "baseline 4주 미만 구간 오탐↑"을 경고한다.
# 표본이 이 값 미만인 기준선에서 나온 급락은 **기록은 하되 발행하지 않는다**(아래 성숙도 게이트).
MATURE_SAMPLES = 28

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
#
# ── 성숙도 게이트 (실측 2026-07-29) ──────────────────────────────────────────
#  기준선 표본이 MATURE_SAMPLES 미만이면 **기록은 하되 발행하지 않는다.**
#  알림은 되돌릴 수 없는데, 미성숙 기준선의 μ·σ는 아직 "평상시"를 대표하지 못한다.
#  실측 근거: 2026-07-29 기준 가격 이력이 07-13에 시작해 최대 15일이고, 컬리는 07-14~07-20
#  7일 연속 결손으로 9일뿐이었다. 그 상태로 탐지된 7건 중 6건이 **N=8인 컬리**였다 —
#  가장 미성숙한 소스에서 알림이 나갈 뻔했다(ai-spec §4.1 오탐 구간).
#  게이트는 **시계열별**로 건다. 소스마다 성숙 속도가 달라, 한쪽이 늦다고 다른 쪽을
#  막을 이유가 없다. 이력이 쌓이면 자동으로 풀린다.

_DAILY_SQL = """
-- (품목·소스·일자)별 **최저 100g 단가 1건**과 그 근거(실제 상품·실제가·시점)를 함께 가져온다.
--
-- ⚠️ 일자는 **KST 영업일**이다. DB 세션 TZ 가 UTC 라 `crawled_at::date` 로 끊으면 한 UTC 날짜에
--    **서로 다른 KST 날짜 2개**가 섞인다(실측 2026-07-29: 최근 7일 전부 2개씩 섞임).
--      · 컬리 03:30 KST = 18:30 UTC **전날**
--      · 오아시스 04:10 KST = 19:10 UTC **전날** / 13:10 KST = 04:10 UTC 같은날
--    그대로 두면 "오늘 최저가"가 오아시스 오후 + 다음날 새벽 + 다음날 컬리의 혼합이 되어
--    이동평균의 입력이 하루 단위가 아니게 된다(μ·σ 왜곡).
-- 집계로 단가만 남기면 price_anomaly 가 요구하는 근거 스냅샷을 채울 수 없다
-- (roadmap §6 "합성금액 금지 — 화면엔 실상품+실가격+용량+시점").
WITH px AS (
  SELECT rp.item_id,
         rp.source,
         (p.crawled_at AT TIME ZONE 'Asia/Seoul')::date  AS d,   -- ⚠️ KST 영업일
         p.price / rp.weight_g * 100             AS won_per_100g,
         p.retail_product_id,
         p.price,
         p.crawled_at,
         p.discount_rate,
         row_number() OVER (
           PARTITION BY rp.item_id, rp.source, (p.crawled_at AT TIME ZONE 'Asia/Seoul')::date
           ORDER BY p.price / rp.weight_g * 100, p.crawled_at DESC
         ) AS rn
  FROM retail_price p
  JOIN retail_product rp ON rp.id = p.retail_product_id
  WHERE rp.item_id IS NOT NULL
    AND rp.weight_g > 0
    AND p.price > 0
    AND p.is_sold_out IS NOT TRUE
    AND p.crawled_at >= now() - make_interval(days => %(window)s)
)
SELECT px.item_id, im.canonical_name, px.source, px.d, px.won_per_100g, px.discount_rate,
       px.retail_product_id, px.price, px.crawled_at
FROM px
JOIN item_master im ON im.item_id = px.item_id
WHERE px.rn = 1
ORDER BY px.item_id, px.source, px.d
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
    # ── 근거 스냅샷 — 합성금액 금지(roadmap §6). price_anomaly 가 NOT NULL 로 요구한다.
    retail_product_id: int    # 그 단가를 만든 실제 상품
    price: float              # 실제 판매가(정규화 전)
    crawled_at: str           # 그 가격을 관측한 시점


def _series(rows) -> dict[tuple[int, str], dict]:
    """(item_id, source) → {name, points:[(date, 단가, 할인율, 상품id, 실제가, 관측시점)]}"""
    out: dict[tuple[int, str], dict] = {}
    for item_id, name, source, d, w100, disc, rpid, price, crawled in rows:
        e = out.setdefault((item_id, source), {"name": name, "points": []})
        e["points"].append((d, float(w100), disc, rpid, float(price), crawled))
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
        hist_vals = [w for _, w, *_ in hist]
        cur_date, cur_price, cur_disc, cur_rpid, cur_raw_price, cur_crawled = cur

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
            retail_product_id=cur_rpid, price=round(cur_raw_price, 2),
            crawled_at=cur_crawled.isoformat() if hasattr(cur_crawled, "isoformat") else str(cur_crawled),
        ))
    found.sort(key=lambda a: a.drop_pct, reverse=True)   # 체감 큰 순(정책 ①)
    return found if top_n is None else found[:top_n]



# ── 영속화 ───────────────────────────────────────────────────────────────────
# 왜 남기는가: ① 알림 근거 재현("평소 5,200원인데 오늘 3,990원") ② 오탐률 사후 측정 →
# 임계 재조정 ③ 배치 재실행 멱등(UNIQUE). 스키마·근거는
# docs/prd/migrations/2026-07-29_price_anomaly.sql · 2026-07-29b_price_baseline_per_source.sql.
#
# ⚠️ 기준선은 **(품목, 소스)별**이다. 두 소매의 100g 단가가 중앙값 41.9% 달라, 합치면 σ가
#    중앙값 2.08배 부풀어 z가 절반이 되고 탐지가 죽는다(실측 2026-07-29).
_BASELINE_UPSERT = """
INSERT INTO price_baseline (item_id, source, as_of, window_days, mean_100g, stddev_100g,
                            min_100g, obs_count)
VALUES (%(item_id)s, %(source)s, %(as_of)s, %(window)s, %(mean)s, %(sd)s, %(min)s, %(n)s)
ON CONFLICT (item_id, source, as_of) DO UPDATE
   SET mean_100g = EXCLUDED.mean_100g, stddev_100g = EXCLUDED.stddev_100g,
       min_100g = EXCLUDED.min_100g, obs_count = EXCLUDED.obs_count,
       window_days = EXCLUDED.window_days, computed_at = now()
"""

_ANOMALY_INSERT = """
INSERT INTO price_anomaly (item_id, detected_on, source, retail_product_id, crawled_at,
                           price, price_100g, z_score, baseline_mean, baseline_stddev,
                           is_record_low, discount_rate, drop_pct)
VALUES (%(item_id)s, %(detected_on)s, %(source)s, %(rpid)s, %(crawled_at)s,
        %(price)s, %(price_100g)s, %(z)s, %(mean)s, %(sd)s,
        %(record_low)s, %(discount)s, %(drop_pct)s)
ON CONFLICT (item_id, detected_on, source) DO UPDATE
   SET price = EXCLUDED.price, price_100g = EXCLUDED.price_100g, z_score = EXCLUDED.z_score
RETURNING id
"""


def persist_baselines(conn, rows, window_days: int, min_samples: int) -> int:
    """모든 (품목, 소스) 시계열의 μ·σ·표본수를 기록. 탐지 여부와 무관하게 남긴다.

    obs_count 가 **오탐 게이트의 데이터 근거**다 — 표본이 적은 구간을 코드 상수가 아니라
    기록된 수치로 판정할 수 있어야 한다(ai-spec §4.1 "4주 미만 오탐↑").
    """
    n = 0
    with conn.cursor() as cur:
        for (item_id, source), e in _series(rows).items():
            vals = [w for _, w, *_ in e["points"]]
            if len(vals) < min_samples:
                continue
            as_of = e["points"][-1][0]
            cur.execute(_BASELINE_UPSERT, {
                "item_id": item_id, "source": source, "as_of": as_of, "window": window_days,
                "mean": round(st.mean(vals), 2), "sd": round(st.pstdev(vals), 2),
                "min": round(min(vals), 2), "n": len(vals),
            })
            n += 1
    return n


def persist_anomalies(conn, found: list[Anomaly]) -> list[int]:
    """채택된 이상치를 기록하고 id 목록을 돌려준다(발행 후 published_at 갱신에 쓴다)."""
    ids = []
    with conn.cursor() as cur:
        for a in found:
            cur.execute(_ANOMALY_INSERT, {
                "item_id": a.item_id, "detected_on": a.observed_at, "source": a.source,
                "rpid": a.retail_product_id, "crawled_at": a.crawled_at,
                "price": a.price, "price_100g": a.price_100g, "z": a.z_score,
                "mean": a.baseline_mean, "sd": a.baseline_std,
                "record_low": a.is_record_low, "discount": a.discount_rate,
                "drop_pct": a.drop_pct,
            })
            ids.append(cur.fetchone()[0])
    return ids


def mark_published(conn, ids: list[int]) -> None:
    """Kafka 발행 성공분만 표시. 미발행분은 published_at IS NULL 로 남아 재시도 대상이 된다."""
    if not ids:
        return
    with conn.cursor() as cur:
        cur.execute("UPDATE price_anomaly SET published_at = now() WHERE id = ANY(%s)", (ids,))


def run(*, window=WINDOW_DAYS, z=Z_THRESHOLD, min_drop=MIN_DROP_PCT,
        min_samples=MIN_SAMPLES, top_n=TOP_N, json_path=None,
        emit_kafka=False, persist=False, emit_direct=False,
        mature_samples=MATURE_SAMPLES, allow_immature=False,
        has_time=None, emit_line=print) -> dict:
    """이상탐지 본체. **CLI 와 Lambda 가 같이 쓴다.**

    ⚠️ 출력 인자 이름이 다른 배치와 다르다(`emit` → **`emit_line`**). 이 파일에는
    **`--emit`(Kafka 발행) 플래그가 이미 있어서** 같은 이름을 쓰면 *"발행"* 과 *"출력"* 이 섞인다.
    CLI 플래그는 한 글자도 안 바꿨다 — 바뀐 것은 `run()` 의 키워드 이름뿐이다.

    has_time — **fan-out 항목 사이**마다 "시간이 남았나"를 묻는다. None 이면 안 본다(CLI).
    🟢 중단이 안전한 이유 = 남은 건의 `published_at` 이 **NULL 로 남아 다음 실행이 재시도**한다
    (detect:250 의 성질 그대로). `price_alert_sent` PK + 7일 쿨다운이 중복 알림도 막는다.

    반환에 `fanout_failed` 가 있다. **종료코드로 바꾸는 것은 호출자 몫** —
    CLI 는 `sys.exit(1)`, Lambda 는 예외를 던진다(런타임이 실패로 세야 재시도·알람이 걸린다).
    """
    persist = persist or emit_kafka or emit_direct

    with connect() as conn:
        rows = conn.execute(_DAILY_SQL, {"window": window}).fetchall()

    series_n = len(_series(rows))
    top_n = top_n or None
    matched = detect(rows, z, min_drop, min_samples, top_n=None)
    found = matched if top_n is None else matched[:top_n]

    emit_line(f"시계열 {series_n}개 · 스캔 {len(rows):,}행 "
              f"(window={window}일 · z<={z} · drop>={min_drop}% · N>={min_samples})")
    capped = f" → 상위 {len(found)}건 채택(TOP_N={top_n})" if top_n and len(matched) > top_n else ""
    emit_line(f"조건 충족 {len(matched)}건{capped}")
    for a in found:
        flag = " 🔻역대최저" if a.is_record_low else ""
        disc = f" · 할인 {a.discount_rate}%" if a.discount_rate else ""
        emit_line(f"  [{a.source:6s}] {a.canonical_name}(item={a.item_id}) "
                  f"{a.price_100g:,.0f}원/100g  ▼{a.drop_pct:.0f}% (평균 {a.baseline_mean:,.0f}) "
                  f"z={a.z_score} N={a.samples}{flag}{disc}")

    if json_path:
        # 🔴 Lambda 에서 쓰기 가능한 곳은 `/tmp` 뿐이다. 호출자가 그 경로를 준다.
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump([asdict(a) for a in found], f, ensure_ascii=False, indent=1)
        emit_line(f"→ {json_path}")

    result = {"series": series_n, "scanned": len(rows), "matched": len(matched),
              "found": len(found), "persisted": 0, "ripe": 0, "gated": 0,
              "published": 0, "fanout_done": 0, "fanout_made": 0, "fanout_failed": 0,
              "stopped_early": False}

    anomaly_ids: list[int] = []
    if persist:
        with connect() as conn:
            nb = persist_baselines(conn, rows, window, min_samples)
            anomaly_ids = persist_anomalies(conn, found)
            conn.commit()
        result["persisted"] = len(anomaly_ids)
        emit_line(f"→ price_baseline {nb}건 · price_anomaly {len(anomaly_ids)}건 기록")

    # ── 발행 준비 (두 경로 공통) ─────────────────────────────────────────────
    # 🔴 이 계산은 **반드시 두 발행 블록 밖**에 있어야 한다 (#641).
    #    종전에는 `if args.emit:` 안에 있어서 `--emit-direct` 단독 실행이 NameError 로 죽었고,
    #    그렇다고 `ripe` 만 밖으로 빼면 **성숙도 게이트가 따라 나오지 않아** 미성숙 기준선에서
    #    나온 오탐이 사용자 알림으로 **직접** 간다. 게이트와 한 몸으로 옮긴다.
    id_by_idx: dict[int, int] = {}
    ripe: list = []
    if emit_kafka or emit_direct:
        # ── 성숙도 게이트 — 미성숙 기준선에서 나온 건은 기록만 하고 발행하지 않는다.
        id_by_idx = dict(enumerate(anomaly_ids))
        ripe = [(i, a) for i, a in enumerate(found)
                if allow_immature or a.samples >= mature_samples]
        gated = len(found) - len(ripe)
        result["ripe"], result["gated"] = len(ripe), gated
        if gated:
            emit_line(f"⚠️  성숙도 게이트: {gated}건 발행 제외 "
                      f"(표본 < {mature_samples}일 — 기준선이 아직 '평상시'를 대표하지 못한다)")
        if not ripe:
            emit_line("→ 발행 대상 0건. 이력이 더 쌓이면 자동으로 풀린다"
                      " (검증 목적이면 --allow-immature).")
            return result

    if emit_kafka:
        # 발행은 여기까지만 — "누구에게 보낼지"는 fan-out 컨슈머가 price_watch를 보고 정한다.
        # 탐지 배치가 유저를 알 필요가 없어야 재실행·백필이 안전하다.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stream"))
        from produce_price_anomaly import emit_anomalies      # noqa: E402

        # 영속화로 받은 price_anomaly.id 를 이벤트에 실어 보낸다 — 컨슈머가 price_alert_sent 에
        # 발송 이력을 남기려면 FK 값이 필요하다.
        payloads = []
        anomaly_ids = []
        for i, a in ripe:
            pl = asdict(a)
            if i in id_by_idx:
                pl["db_id"] = id_by_idx[i]
                anomaly_ids.append(id_by_idx[i])
            payloads.append(pl)
        sent = emit_anomalies(payloads)
        # 발행이 성공한 뒤에만 표시한다 — emit_anomalies 는 미전달 시 DeliveryIncomplete 를 던지므로
        # 여기 도달했다는 것은 전량 전달됐다는 뜻이다.
        with connect() as conn:
            mark_published(conn, anomaly_ids)
            conn.commit()
        result["published"] = sent
        emit_line(f"→ Kafka price.anomaly.detected 발행 {sent}건 (published_at 기록 {len(anomaly_ids)}건)")

    if emit_direct:
        # C-88 — Kafka 를 거치지 않고 fan-out SQL 을 여기서 실행한다.
        # 🟢 컨슈머의 정책·멱등을 **그대로 재사용**한다(재구현 아님): price_alert_sent PK +
        #    7일 쿨다운 + price_anomaly EXISTS 가드가 전부 그 SQL 안에 있다.
        # 🔴 published_at 은 fan-out 이 끝난 뒤에만 찍는다 — 실패분이 NULL 로 남아 재실행 대상이
        #    되는 성질(detect:250)을 Kafka 경로와 동일하게 유지한다.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stream"))
        from consume_price_anomaly import fanout              # noqa: E402
        from produce_price_anomaly import build_anomaly_event  # noqa: E402

        made = done = seen = 0
        with connect() as conn, conn.cursor() as cur:
            for i, a in ripe:
                # 시간 가드는 **항목 사이**에 둔다. 남은 건은 published_at 이 NULL 로 남아
                # 다음 실행이 이어받는다 — 알림 중복은 쿨다운이 막는다.
                if has_time is not None and not has_time():
                    result["stopped_early"] = True
                    emit_line(f"⏱ 시간 상한 임박 — {seen}/{len(ripe)} 에서 자진 중단"
                              f"(남은 건은 published_at NULL 로 다음 실행이 재시도)")
                    break
                seen += 1
                pl = asdict(a)
                if i in id_by_idx:
                    pl["db_id"] = id_by_idx[i]
                ev = build_anomaly_event(pl)                  # Kafka 경로와 같은 계약
                try:
                    made += fanout(cur, ev)
                except Exception as exc:      # noqa: BLE001 — 1건 실패가 나머지를 막지 않는다
                    conn.rollback()
                    emit_line(f"⚠️  fan-out 실패 item_id={pl.get('item_id')} ({type(exc).__name__})")
                    continue
                done += 1
                if i in id_by_idx:
                    mark_published(conn, [id_by_idx[i]])
                conn.commit()
        result["fanout_done"], result["fanout_made"] = done, made
        # 🔴 자진 중단분은 **실패로 세지 않는다** — 시도조차 안 한 건이라 재시도 대상이지 오류가 아니다.
        result["fanout_failed"] = seen - done
        emit_line(f"→ 직접 fan-out {done}/{len(ripe)}건 · 알림 {made}건 생성 (Kafka 미경유)")

    return result


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
                    help="탐지 결과를 Kafka price.anomaly.detected 로 발행(기본: 미발행). --persist 를 함의")
    # 근거를 DB에 남긴다. --emit 은 이를 함의한다 — 근거 없이 알림만 나가면 "왜 이게 급락인가"에
    # 답할 수 없고 오탐률도 사후 측정할 수 없다.
    ap.add_argument("--persist", action="store_true",
                    help="price_baseline·price_anomaly 에 기준선·이상치 기록(기본: 미기록)")
    ap.add_argument("--mature-samples", type=int, default=MATURE_SAMPLES,
                    help="발행 최소 표본(성숙도 게이트). 미만은 기록만 하고 발행 제외")
    ap.add_argument("--allow-immature", action="store_true",
                    help="성숙도 게이트를 무시하고 발행(검증용 — 오탐을 감수한다는 뜻)")
    # 🔴 C-88 — AWS 에는 Kafka 가 없다(C-44). 종전 경로(Kafka → price-anomaly-notifier → PG)의
    #    종착지가 notify.notification 이라, 중간을 걷어내고 이 배치가 직접 fan-out 한다.
    #    별도 인자인 이유 = 기존 --emit 을 **한 글자도 안 바꾼다**(C-72·C-83 온프렘 동결).
    #    🟢 사본 CronJob 으로 1회 검증하기에 특히 안전하다 — price_alert_sent PK + 7일 쿨다운이
    #       중복 알림을 구조적으로 막아 기존 컨슈머를 그대로 둔 채 돌려볼 수 있다(C-72 ②).
    ap.add_argument("--emit-direct", action="store_true",
                    help="Kafka 대신 fan-out SQL 을 직접 실행해 알림을 만든다(C-88). --persist 를 함의")
    args = ap.parse_args()
    # 🔴 배타 — 같이 주면 같은 이상치가 Kafka 로도 가고 직접 fan-out 도 된다.
    #    price_alert_sent PK 가 중복 알림 자체는 막지만, **어느 경로가 발행했는지 알 수 없어**
    #    장애 때 추적이 끊긴다. C-88 의 "목적지는 하나" 원칙을 CLI 에서도 지킨다.
    if args.emit and args.emit_direct:
        ap.error("--emit 과 --emit-direct 는 함께 쓸 수 없다 (목적지는 하나 — C-88)")

    r = run(window=args.window, z=args.z, min_drop=args.min_drop,
            min_samples=args.min_samples, top_n=args.top_n, json_path=args.json,
            emit_kafka=args.emit, persist=args.persist, emit_direct=args.emit_direct,
            mature_samples=args.mature_samples, allow_immature=args.allow_immature)

    # 🔴 실패가 있으면 **비영 종료**한다 (비판 검토 🔴3). CronJob 은 종료코드로만 성패를 알고,
    #    per-item except 로 넘기면 전량 실패해도 Completed 로 보고돼 알림이 통째로 멈춘 걸
    #    아무도 모른다. Kafka 경로는 DeliveryIncomplete 로 이미 1을 내므로 관측을 대칭으로 맞춘다.
    #    published_at IS NULL 재시도 성질은 그대로다 — 다만 **재시도를 트리거할 신호**가 생긴다.
    if r["fanout_failed"]:
        print(f"🔴 {r['fanout_failed']}건 fan-out 실패 — 종료코드 1")
        sys.exit(1)


if __name__ == "__main__":
    main()
