"""메모리 안전 재학습·평가 — 384Mi 파드에서 OOM 없이 대용량 학습 (#535 부트스트랩).

안전장치(시간↑ 대신 메모리 보장):
- **서버사이드 커서**로 청크 스트리밍 → fetchall 금지(154만 행을 한 번에 안 올림).
- **유저 범위 캡**(--users): ev를 user_id<base+users로 제한 → DB 조인비용·행수 동시 축소, 완전한 그룹 유지.
- **청크→float32 즉시 변환** 후 원시 dict 폐기 → dict 누적(수백MB) 회피. group은 int32 id.
- baseline(rule_score)은 X[:,3]에서 취함(dict 미보관).

읽기(평가): python ranking_safe.py --users 12000
저장(활성화): python ranking_safe.py --users 12000 --save   (모델 저장 + /reload)

⚠️ 합성 데이터 → 파이프라인·신호학습 검증이지 실세계 성능 아님(발표 표기 그대로).
"""
from __future__ import annotations

import argparse
import gc
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import psycopg

import evaluate
import features
import train
from features import EXTRACT_SQL, FEATURE_COLUMNS, raw_to_feature_rows

BASE_USER = 9_000_001
RULE_IDX = FEATURE_COLUMNS.index("rule_score")   # baseline = 규칙점수 열


def _dsn() -> str:
    return (f"host={os.environ.get('PGHOST','')} port={os.environ.get('PGPORT','5432')} "
            f"dbname={os.environ.get('PGDATABASE','foodbudget')} user={os.environ.get('PGUSER','fbapp')} "
            f"password={os.environ.get('PGPASSWORD','')}")


def load_stream(conn, since, umax, chunk):
    """서버사이드 커서로 스트리밍 → (X float32, y int8, g int32) 그룹 정렬본. 메모리 바운드."""
    sql = EXTRACT_SQL.replace("where i.shown_at >= %(since)s",
                              "where i.shown_at >= %(since)s and i.user_id < %(umax)s")
    Xs, ys, gs, gmap, n = [], [], [], {}, 0
    with conn.cursor(name="rank_stream") as cur:      # named=서버사이드→클라 메모리 바운드
        cur.itersize = chunk
        cur.execute(sql, {"since": since, "umax": umax})
        cols = None
        while True:
            batch = cur.fetchmany(chunk)
            if not batch:
                break
            if cols is None:
                cols = [d.name for d in cur.description]
            rows = raw_to_feature_rows([dict(zip(cols, r)) for r in batch])
            Xs.append(np.array([[float(r.get(c, 0.0)) for c in FEATURE_COLUMNS] for r in rows],
                               dtype=np.float32))
            ys.append(np.fromiter((int(r["relevance"]) for r in rows), dtype=np.int8, count=len(rows)))
            gs.append(np.fromiter((gmap.setdefault(r["group"], len(gmap)) for r in rows),
                                  dtype=np.int32, count=len(rows)))
            n += len(rows)
            del rows, batch
            if n % 100_000 < chunk:
                print(f"  스트리밍 {n} 행 / 그룹 {len(gmap)} …", flush=True)
    X = np.concatenate(Xs); y = np.concatenate(ys); g = np.concatenate(gs)
    del Xs, ys, gs; gc.collect()
    order = np.argsort(g, kind="stable")              # 그룹 연속(LambdaMART 요건)
    return X[order], y[order], g[order]


def main() -> int:
    ap = argparse.ArgumentParser(description="메모리 안전 랭킹 재학습·평가")
    ap.add_argument("--users", type=int, default=12000, help="학습에 쓸 유저 범위(base부터). ↑=데이터↑·메모리↑")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--chunk", type=int, default=20000, help="스트리밍 배치 크기")
    ap.add_argument("--base", type=int, default=BASE_USER)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--save", action="store_true", help="모델 저장(/models/ranker.pkl) + 서빙 /reload")
    args = ap.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    umax = args.base + args.users
    print(f"[safe] 추출·학습 (유저<{umax}, since={since:%Y-%m-%d}) — 스트리밍, 수분 소요…", flush=True)
    with psycopg.connect(_dsn(), connect_timeout=8) as conn:
        X, y, g = load_stream(conn, since, umax, args.chunk)

    G = int(g[-1]) + 1 if len(g) else 0
    print(f"[safe] 로드 완료: {len(y)} 행 · {G} 그룹 · X {X.nbytes/1e6:.0f}MB(float32)")
    if G < 8:
        print("그룹 부족(<8) — 시드 확인"); return 1

    cut = int(G * 0.75)                                # 그룹 id 기준 75/25 분할(정렬돼 있어 임계로 분리)
    tr, te = g < cut, g >= cut
    model = train.train(X[tr], y[tr], g[tr], random_state=args.seed)
    res = evaluate.compare(y[te], model.predict(X[te]), X[te][:, RULE_IDX], g[te], k=10)
    m, b = res["model"], res["baseline"]

    print(f"\n{'지표':<10}{'규칙baseline':>14}{'ML모델':>12}{'Δ':>11}")
    print("-" * 47)
    for k in ("ndcg@k", "map@k", "mrr"):
        print(f"{k:<10}{b[k]:>14.4f}{m[k]:>12.4f}{m[k]-b[k]:>+11.4f}")
    print("-" * 47)
    print(f"NDCG lift (ML/규칙): {res['ndcg_lift']*100:+.1f}%")

    est = getattr(model, "_m", model)
    imp = getattr(est, "feature_importances_", None)
    if imp is not None:
        tot = float(np.sum(imp)) or 1.0
        for name, v in sorted(zip(FEATURE_COLUMNS, imp), key=lambda t: -t[1])[:8]:
            print(f"  {name:22} {v/tot:6.1%} {'█'*int(round(v/tot*30))}")

    if args.save:
        path = os.environ.get("RANKING_MODEL_PATH", "/models/ranker.pkl")
        train.save_model(model, path)
        print(f"\n[safe] 모델 저장 → {path}")
        try:
            import urllib.request as u
            r = u.urlopen(u.Request("http://localhost:8009/reload", method="POST"), timeout=60)
            print(f"[safe] /reload → {r.read().decode()[:120]}")
        except Exception as exc:  # noqa: BLE001
            print(f"[safe] /reload 실패({type(exc).__name__}) — 파드 재기동/수동 reload로 반영")
    else:
        print("\n[해석] ML NDCG>규칙 + 개인화 피처 상위면 학습효과 有. 활성화하려면 --save 로 재실행.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
