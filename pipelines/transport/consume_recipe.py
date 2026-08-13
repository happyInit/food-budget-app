"""recipe-refiner (S3/SQS) — incoming/recipe/** → process_recipe → PG.

구 `pipelines/stream/consume_recipe.py`(Kafka)의 대체물. 전처리 로직은 배치와 동일한
`load_10k_recipe.process_recipe` 를 그대로 쓴다 — 바뀐 것은 운반뿐이다.

env: MP_SQS_URL(필수) · MP_CRAWL_BUCKET · CONSUME_IDLE_EXIT(초, 미설정 시 상주)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from _refinery import run                                                  # noqa: E402
from gazetteer import load_gazetteer, load_meat_canons, make_matcher       # noqa: E402
from load_10k_recipe import process_recipe                                 # noqa: E402

GROUP = "recipe-refiner"
STREAM = "recipe"
COMMIT_EVERY = 100


def build_context(cur):
    return make_matcher(load_gazetteer(cur), load_meat_canons(cur))


def process(cur, match, source, payload):  # noqa: ARG001 — source 는 레시피 적재에 안 쓰인다
    _, _, hit, total = process_recipe(cur, payload, match)
    return (hit, total)


if __name__ == "__main__":
    run(group=GROUP, stream=STREAM, commit_every=COMMIT_EVERY,
        build_context=build_context, process=process)
