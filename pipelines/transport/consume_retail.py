"""retail-refiner (S3/SQS) — incoming/retail/** → 전처리 → 현재 테이블.

구 `pipelines/stream/consume_retail.py`(Kafka)의 대체물. 전처리 로직은 **그대로 재사용**한다
(`load_retail.stage_record` · `refine_record`) — 바뀐 것은 운반뿐이다.

🔴 두 파일은 **전환 기간에 나란히 돈다.** Kafka 쪽은 손대지 않았으므로 되돌리기가
   "Deployment 의 command 를 원래대로" 한 줄이고, 카나리 중에는 같은 레코드가 양쪽으로 들어와도
   적재가 멱등이라 아무 일도 일어나지 않는다.

env: MP_SQS_URL(필수) · MP_CRAWL_BUCKET · CONSUME_IDLE_EXIT(초, 미설정 시 상주)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from _refinery import run                                              # noqa: E402
from load_retail import build_matcher, refine_record, stage_record     # noqa: E402

GROUP = "retail-refiner"
STREAM = "retail"
COMMIT_EVERY = 200


def build_context(cur):
    return build_matcher(cur)  # gazetteer 1회 로드(큐레이션 변경 시 재시작)


def process(cur, match, source, payload):
    rid = stage_record(cur, source, payload)                 # crawl_raw 원본 durable
    iid, _ = refine_record(cur, source, payload, match)      # retail_product / retail_price
    if rid is not None:
        cur.execute("update crawl_raw set processed_at=now() where id=%s", (rid,))
    return (1 if iid is not None else 0, 1)


if __name__ == "__main__":
    run(group=GROUP, stream=STREAM, commit_every=COMMIT_EVERY,
        build_context=build_context, process=process)
