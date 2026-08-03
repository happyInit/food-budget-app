"""① 스냅샷 export — CRF 재료 NER 학습 코퍼스를 PG에서 1회 벌크로 떠서 로컬 파일로.

모델 X + 스냅샷 방식(`docs/prd/ner-requirements-to-data.md` §2.1 #4·§2.3):
학습은 이 로컬 스냅샷으로 오프라인 진행 — PG에 반복 쿼리하지 않는다(1회 수 MB).

- 타깃(라벨 붙일 대상): COOKRCP01 자유텍스트(`ingredient_raw`, ner_status='RAW')
- 사전(약지도 라벨 소스): EPIS gold 재료명(`ingredient_name`, ner_status='LABELED')
- 10K(만개)는 TDM 옵트아웃이라 제외(`source != '10K'`, ner-training-data-spec §2)

산출: data/corpus.jsonl (타깃) · data/dict.txt (사전) · data/snapshot.meta.json (시점)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
import psycopg

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")          # 레포 루트 .env의 PG* 재사용(pipelines/ingest 컨벤션)
_OUT = Path(__file__).parent / "data"
_OUT.mkdir(exist_ok=True)

TARGET_SQL = """
select r.src_recipe_id, ri.seq, ri.ingredient_raw
from recipe_ingredient ri
join recipe r on r.id = ri.recipe_id
where r.source = 'COOKRCP01' and ri.ner_status = 'RAW'
  and ri.ingredient_raw is not null and length(trim(ri.ingredient_raw)) > 0
order by r.src_recipe_id, ri.seq
"""

DICT_SQL = """
select distinct ri.ingredient_name
from recipe_ingredient ri
join recipe r on r.id = ri.recipe_id
where r.source = 'EPIS' and ri.ner_status = 'LABELED'
  and ri.ingredient_name is not null and length(trim(ri.ingredient_name)) > 0
"""

# 사전 증강(공공데이터만): item_master canonical + alias. 10K은 TDM 옵트아웃이라 제외.
# span 탐지용이라 육류 코드 뭉갬(PR #54)과 무관.
ITEM_MASTER_SQL = """
select canonical_name as term from item_master where canonical_name is not null
union
select alias as term from item_alias where alias is not null
"""


def _connect():
    return psycopg.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "foodbudget"),
        user=os.environ.get("PGUSER", "fbapp"),
        password=os.environ.get("PGPASSWORD", ""),
    )


def main() -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(TARGET_SQL)
        targets = cur.fetchall()
        cur.execute(DICT_SQL)
        dict_terms = [r[0].strip() for r in cur.fetchall()]
        cur.execute(ITEM_MASTER_SQL)
        im_terms = [r[0].strip() for r in cur.fetchall() if r[0]]

    with (_OUT / "corpus.jsonl").open("w", encoding="utf-8") as f:
        for src_recipe_id, seq, raw in targets:
            f.write(json.dumps(
                {"src_recipe_id": str(src_recipe_id), "seq": seq, "text": raw},
                ensure_ascii=False) + "\n")

    with (_OUT / "dict.txt").open("w", encoding="utf-8") as f:
        f.write("\n".join(dict_terms))
    with (_OUT / "dict_item_master.txt").open("w", encoding="utf-8") as f:
        f.write("\n".join(im_terms))

    meta = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_filter": "COOKRCP01(RAW) target + EPIS(LABELED)/item_master dict, source != '10K'",
        "n_target_rows": len(targets),
        "n_dict_epis": len(dict_terms),
        "n_dict_item_master": len(im_terms),
    }
    (_OUT / "snapshot.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"export 완료: 타깃 {len(targets)}행 · EPIS사전 {len(dict_terms)}개 · "
          f"item_master사전 {len(im_terms)}개 → {_OUT}")


if __name__ == "__main__":
    main()
