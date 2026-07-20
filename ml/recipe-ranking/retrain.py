"""재학습 배치 — activity 클릭스트림 → 랭커 학습 → 모델 저장(서빙이 로드).

데이터가 쌓이면 사람 개입 없이 주기적으로 모델을 갱신하는 자동화 조각.
  extract(피처행) → to_matrix → train → save_model(RANKING_MODEL_PATH)
서빙(serve.py)과 **같은 모델 경로를 공유 볼륨**으로 공유 → 저장 즉시 다음 서빙 기동/재로드에 반영.

안전장치(전부 비치명 — 실패해도 기존 모델·서빙 무손상):
  · activity 스키마 미마이그레이션 → skip(코드는 준비됨, 데이터 트랙 대기).
  · 학습행 < MIN_ROWS 또는 그룹 < MIN_GROUPS(콜드스타트) → skip(기존 모델 유지).
  · 학습/저장 예외 → 로깅 후 skip(기존 모델 유지).

실행: `python retrain.py`(1회, cron) 또는 `python retrain.py --loop 86400`(compose 서비스, 일 1회).
"""
from __future__ import annotations

import argparse
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from extract import activity_ready, connect, extract_feature_rows
from features import to_matrix
from train import save_model, train

MIN_ROWS = int(os.environ.get("RETRAIN_MIN_ROWS", "200"))       # 이만큼은 쌓여야 학습 의미
MIN_GROUPS = int(os.environ.get("RETRAIN_MIN_GROUPS", "20"))    # 노출요청(그룹) 최소수
DEFAULT_DAYS = int(os.environ.get("RETRAIN_DAYS", "90"))        # 학습 스냅샷 창(최근 N일)
# 재학습 성공 시 서빙에 새 모델 반영을 푸시(무인 자동화의 마지막 고리). 미설정이면 skip → 수동 재기동 때 반영.
#   compose 기본값=형제 서빙(http://ranking-serving:8009/reload) — 같은 프로필·네트워크라 항상 도달 가능.
RELOAD_URL = os.environ.get("RANKING_RELOAD_URL", "").strip()


def _log(msg: str) -> None:
    print(f"[retrain {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}] {msg}", flush=True)


def _trigger_serving_reload() -> None:
    """재학습 성공 후 서빙 /reload를 호출해 새 모델을 즉시 반영(best-effort, 비치명).
    실패해도 모델은 이미 저장됨 → 다음 서빙 재기동 때 반영(무손상). docker.sock 불필요(HTTP)."""
    if not RELOAD_URL:
        return
    try:
        with urllib.request.urlopen(urllib.request.Request(RELOAD_URL, method="POST"), timeout=10) as r:
            _log(f"서빙 재적재 트리거 성공 → {RELOAD_URL} {r.read().decode()[:160]}")
    except Exception as exc:  # noqa: BLE001 — 트리거 실패는 비치명(모델은 저장됨, 서빙 무손상)
        _log(f"서빙 재적재 트리거 실패({type(exc).__name__}) — 다음 서빙 재기동 때 반영.")


def retrain_once(days: int = DEFAULT_DAYS, model_path: str | None = None) -> int:
    """1회 재학습. 반환 0=갱신, 2=데이터부족/미마이그레이션(skip), 1=오류. 어떤 경우도 기존 모델 무손상."""
    path = model_path or os.environ.get("RANKING_MODEL_PATH", "/models/ranker.pkl")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        with connect() as conn:
            if not activity_ready(conn):
                _log("activity 스키마 미마이그레이션 — skip(스키마 적용·데이터 축적 후 자동 학습).")
                return 2
            rows = extract_feature_rows(conn, since)
    except Exception as exc:  # noqa: BLE001 — DB 장애 → 비치명 skip
        _log(f"추출 실패({type(exc).__name__}: {str(exc)[:100]}) — 기존 모델 유지.")
        return 1

    X, y, groups = to_matrix(rows)
    n_groups = len(set(groups.tolist())) if len(groups) else 0
    if len(rows) < MIN_ROWS or n_groups < MIN_GROUPS:
        _log(f"학습행 {len(rows)}(<{MIN_ROWS}) / 그룹 {n_groups}(<{MIN_GROUPS}) — 콜드스타트 skip.")
        return 2

    try:
        model = train(X, y, groups)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        save_model(model, path)
    except Exception as exc:  # noqa: BLE001 — 학습/저장 장애 → 기존 모델 유지
        _log(f"학습/저장 실패({type(exc).__name__}: {str(exc)[:100]}) — 기존 모델 유지.")
        return 1
    _log(f"재학습 완료 — 행 {len(rows)}·그룹 {n_groups} → {path} 갱신.")
    _trigger_serving_reload()      # 서빙에 즉시 반영 푸시(미설정/실패면 다음 재기동 때 반영)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS, help="학습 스냅샷 창(최근 N일)")
    ap.add_argument("--loop", type=int, metavar="SEC",
                    help="주기 실행 간격(초). 미지정시 1회 실행 후 종료.")
    args = ap.parse_args()
    try:
        from extract import _load_env
        _load_env()
    except Exception:  # noqa: BLE001
        pass
    if not args.loop:
        return retrain_once(days=args.days)
    _log(f"주기 재학습 시작 — {args.loop}s 간격.")
    while True:                              # 컨슈머/프루너와 동일한 --loop 서비스 패턴
        retrain_once(days=args.days)         # 반환값 무관 — 다음 주기에 재시도
        time.sleep(args.loop)


if __name__ == "__main__":
    raise SystemExit(main())
