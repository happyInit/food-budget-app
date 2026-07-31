"""챗 인사이트 배치 — 데이터가 쌓이면 무인으로 리포트·선호신호·의도학습을 돌린다.

  python run.py                 # 실 chat_message(없으면 skip 안내) 1회
  python run.py --synth         # 합성 데이터로 end-to-end 검증(DB 불필요)
  python run.py --loop 86400    # 주기 실행(compose 서비스, 일 1회)
  python run.py --kind threshold --trigger unanswered-spike

세 산출:
  · reports/chat/daily|threshold/   리포트(데이터 담당)
  · reports/chat/preference-signals/ 선호신호(랭킹 환류)
  · INTENT_MODEL_PATH                의도 분류기(데이터 충분 시)

미마이그레이션/데이터부족은 전부 skip(비치명) — 데이터 흐르면 그대로 가동(prep-ahead).
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone

import intent_model
import preferences
import reports
from _data import load_since


def _log(msg: str) -> None:
    print(f"[chat-insights {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}] {msg}", flush=True)


def run_once(days: int, kind: str, trigger: str | None, use_synth: bool) -> int:
    if use_synth:
        from synth import make_messages
        messages = make_messages()
        _log(f"합성 데이터 {len(messages)}건으로 실행(DB 미접촉).")
    else:
        messages = load_since(days)
        # skip 은 비치명(모듈 독스트링 계약) — 비 0 exit 는 K8s CronJob 에서 매일 Failed 로 집계된다.
        # (.8 compose --loop 상주 시절엔 리턴코드가 무시돼 드러나지 않던 차이)
        if messages is None:
            _log("chat.chat_message 미마이그레이션/장애 — skip(스키마·쓰기경로 #127 대기).")
            return 0
        if not messages:
            _log("최근 대화 0건 — skip(데이터 축적 대기).")
            return 0
        _log(f"chat_message {len(messages)}건 로드(최근 {days}일).")

    # 1) 리포트
    rpath, metrics = reports.generate(messages, kind=kind, trigger=trigger)
    _log(f"리포트 → {rpath} (미응답률 {metrics['unanswered_rate']*100:.1f}%, 갭 {len(metrics['coverage_gap_terms'])}종)")

    # 2) 선호 신호(개인화 환류)
    spath, signals = preferences.generate(messages)
    _log(f"선호신호 → {spath} (유저 {len(signals)}명)")

    # 3) 의도 분류기(데이터 충분 시)
    ok, why = intent_model.can_train(messages)
    if ok:
        model = intent_model.train(messages)
        mpath = os.environ.get("INTENT_MODEL_PATH", "reports/chat/intent_model.pkl")
        os.makedirs(os.path.dirname(mpath) or ".", exist_ok=True)
        intent_model.save(model, mpath)
        _log(f"의도 분류기 학습 → {mpath}")
    else:
        _log(f"의도 분류기 skip({why}) — 규칙 유지.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1, help="daily=1, 분석 창(최근 N일)")
    ap.add_argument("--kind", choices=["daily", "threshold"], default="daily")
    ap.add_argument("--trigger", default=None, help="threshold 트리거명(예: unanswered-spike)")
    ap.add_argument("--synth", action="store_true", help="합성 데이터로 실행(DB 불필요)")
    ap.add_argument("--loop", type=int, metavar="SEC", help="주기 실행 간격(초)")
    args = ap.parse_args()
    if not args.loop:
        return run_once(args.days, args.kind, args.trigger, args.synth)
    _log(f"주기 실행 시작 — {args.loop}s 간격.")
    while True:
        run_once(args.days, args.kind, args.trigger, args.synth)
        time.sleep(args.loop)


if __name__ == "__main__":
    raise SystemExit(main())
