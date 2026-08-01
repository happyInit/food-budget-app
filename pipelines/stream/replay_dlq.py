"""DLQ 재투입 — 격리된 메시지를 원인 수정 후 원본 토픽으로 되돌린다 (#252).

**DLQ 는 다시 넣을 수 있어야 의미가 있다.** 넣기만 하고 못 꺼내면 그냥 느린 삭제다.

    python pipelines/stream/replay_dlq.py --topic retail.crawl.raw       # 미리보기(기본)
    python pipelines/stream/replay_dlq.py --topic retail.crawl.raw --apply
    python pipelines/stream/replay_dlq.py --topic retail.crawl.raw --limit 10 --apply

🔴 **원인을 고치기 전에 재투입하지 마라.** 그대로 다시 DLQ 로 돌아온다(무한 왕복).
   그래서 기본을 **미리보기**로 두었고, 무엇이 왜 격리됐는지(`dlq.error`)를 먼저 보여준다.

## 설계

- **원본 그대로 되돌린다** — key·value 를 가공하지 않는다. `dlq.*` 헤더만 제거하고 원본 헤더는 유지.
  (격리할 때 payload 를 감싸지 않은 이유가 이것이다 — 벗겨낼 게 없어야 재투입이 단순하다.)
- **읽기 전용 소비** — DLQ 토픽의 오프셋을 **커밋하지 않는다.** 재투입이 실패해도 DLQ 는 그대로
  남아 다시 시도할 수 있다. 대신 같은 메시지를 두 번 재투입할 위험이 있으므로
  아래 "중복" 항목을 볼 것.
- **중복**: 컨슈머들이 멱등(upsert·`ON CONFLICT`·`event_id` UNIQUE)이라 재투입 중복은 무해하다.
  그래도 이력을 남기려고 `dlq.replayed_at` 헤더를 붙여 발행한다.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _dlq import DLQ_SUFFIX, dlq_topic  # noqa: E402

GROUP = "dlq-replay"          # 별도 그룹 — 운영 컨슈머 오프셋을 건드리지 않는다
POLL_TIMEOUT = 5.0            # 이 시간 동안 새 메시지가 없으면 끝났다고 본다


def _decode(v: bytes | None) -> str:
    return (v or b"").decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser(description="DLQ 재투입(기본: 미리보기)")
    ap.add_argument("--topic", required=True,
                    help="원본 토픽명(`.dlq` 는 자동으로 붙는다). 예: retail.crawl.raw")
    ap.add_argument("--limit", type=int, help="상위 N건만")
    ap.add_argument("--apply", action="store_true",
                    help="실제로 원본 토픽에 재발행(기본: 미리보기). **원인을 먼저 고칠 것**")
    args = ap.parse_args()

    from confluent_kafka import Consumer, KafkaError  # noqa: PLC0415
    from _kafka import BOOTSTRAP, producer  # noqa: PLC0415

    src = args.topic if args.topic.endswith(DLQ_SUFFIX) else dlq_topic(args.topic)
    dst = src[: -len(DLQ_SUFFIX)]

    c = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": GROUP,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,      # 🔴 커밋하지 않는다 — 실패해도 DLQ 는 남아야 한다
    })
    c.subscribe([src])
    prod = producer() if args.apply else None

    seen = replayed = 0
    reasons: dict[str, int] = {}
    print(f"{src} → {dst}   ({'재투입' if args.apply else '미리보기'})\n")
    try:
        while True:
            msg = c.poll(POLL_TIMEOUT)
            if msg is None:
                break
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                print(f"  kafka 오류: {msg.error()}")
                break
            h = dict(msg.headers() or [])
            err = _decode(h.get("dlq.error")) or "(사유 없음)"
            reasons[err] = reasons.get(err, 0) + 1
            seen += 1
            if seen <= 20:
                print(f"  p{_decode(h.get('dlq.partition'))}@{_decode(h.get('dlq.offset'))} "
                      f"{err}: {_decode(h.get('dlq.detail'))[:70]}")
            if args.apply:
                # dlq.* 만 걷어내고 원본 헤더는 유지 — 재투입 = 원본 재생산
                keep = [(k, v) for k, v in (msg.headers() or []) if not k.startswith("dlq.")]
                keep.append(("dlq.replayed_at", datetime.now(timezone.utc).isoformat().encode()))
                prod.produce(dst, key=msg.key(), value=msg.value(), headers=keep)
                replayed += 1
            if args.limit and seen >= args.limit:
                break
    finally:
        c.close()

    if seen > 20:
        print(f"  … 외 {seen - 20:,}건")
    print(f"\n격리 사유 분포:")
    for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {v:>6,}  {k}")

    if args.apply:
        remaining = prod.flush(30)
        if remaining:
            print(f"\n🔴 미전달 {remaining}건 — 재투입이 완료되지 않았다. DLQ 는 그대로 남아 있다.")
            return 1
        print(f"\n→ {replayed:,}건 재투입 완료. DLQ 오프셋은 커밋하지 않았으므로 "
              f"같은 건이 다시 보인다(멱등이라 중복은 무해).")
    else:
        print(f"\n→ 미리보기(무발행) {seen:,}건. "
              f"**원인을 고친 뒤** --apply 로 재투입할 것 — 안 고치면 그대로 돌아온다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
