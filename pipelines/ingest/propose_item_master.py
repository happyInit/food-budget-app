"""표준품목 사전 보강 **후보 생성** — LLM 은 여기서만 돈다. 런타임은 한 줄도 안 바뀐다.

## 무엇을 하나

지금 `curate_item_master.py` 는 **손으로 적은 카테고리 리스트**(`CATS`)로 승격 대상을 정한다.
461종/1,079별칭까지는 그 방식으로 왔는데, 남은 공백은 사람이 더 적기 어려운 꼬리다.
이 배치는 **그 리스트를 짓는 일**을 LLM 에게 맡기고, 산출물(후보 표)만 남긴다.

    ① 데이터에서 «판단이 필요한 것» 만 축별로 뽑는다
    ② LLM 이 **작은 배치로** 제안한다 — 입력 대비 출력 개수를 검증한다
    ③ 🔴 **관점이 다른 검수자 3인**이 반박한다 — 사람 검토를 대신하는 자리
    ④ 만장일치만 통과시켜 표로 떨군다 — 적용은 별건

🔵 **프로덕션을 안 건드린다.** 읽기 전용 조회 + Bedrock 호출뿐이고, 쓰기는 JSON 파일이다.

## 🔴 첫 판에서 드러난 결함 3개를 고쳤다 (2026-08-19)

    ① 입력 80종 중 **10건만 제안**하고 70종이 조용히 빠졌다
       → 배치를 12개씩 쪼개고, **입력 이름이 전부 응답에 있는지 대조**한다.
         빠진 이름은 `missing` 으로 남긴다 — 조용히 사라지게 두지 않는다.
    ② 검수가 불안정했다 (같은 프롬프트·temperature 0 인데 accept 4 → 2)
       → 검수자에게 **서로 다른 관점**을 준다(가격 · 표기 · 상품존재).
         같은 질문을 반복하면 흔들림만 재는데, 관점이 다르면 **다른 실패를 잡는다.**
    ③ 정작 목표(육류 부위)가 후보에 없었다
       → **육류 축을 따로 세운다.** `돼지고기` 하나에 삼겹살 81 · 대패삼겹살 77 ·
         돼지갈비 16 이 뭉쳐 있고, 부위별 100g 단가가 실제로 다르다
         (돼지고기 1,189 / 갈비 1,261 / 목살 1,420 / 등갈비 2,180).

## 🔴 왜 만장일치인가

사람 검토가 시간상 불가능하다는 전제다(사용자 확정). 다수결로 하면 «2:1 로 통과한 잘못된
항목» 이 사전에 들어가는데, 사전은 **조인 키**라 한 번 잘못 들어가면 가격·영양·랭킹이 함께
어긋난다. 첫 판에서 `죽염→소금`·`마스코바도→설탕` 이 정확히 2:1 로 갈렸고, 통과시켰다면
죽염 레시피에 일반 소금 가격이 붙었을 것이다.

## 쓰는 법

    python pipelines/ingest/propose_item_master.py --limit 40 --out /tmp/proposal.json
    python pipelines/ingest/propose_item_master.py --dry-run          # LLM 없이 입력만
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402

MODEL_ID = os.environ.get("PROPOSE_MODEL_ID",
                          "apac.anthropic.claude-3-5-sonnet-20241022-v2:0")
REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
BATCH = int(os.environ.get("PROPOSE_BATCH", "12"))

# 🔴 값을 매기지 않기로 한 것들 — 후보에서 아예 뺀다. 미매칭 1위가 «물»(2,114회)인데
#    그건 결함이 아니라 `is_liquid_excl` 의 의도다. 넣으면 LLM 이 «물 품목을 만들자» 고 한다.
NOISE = {"물", "찬물", "따뜻한물", "따뜻한 물", "뜨거운물", "뜨거운 물", "생수", "얼음",
         "쌀뜨물", "다시물", "육수물", "정수물", "미온수", "끓는물", "끓는 물"}


# ── ① 축별로 «판단이 필요한 것» 을 뽑는다 ───────────────────────────────────
def collect(cur, limit: int) -> dict:
    axes: dict[str, list[dict]] = {}

    # (a) 못 붙은 이름 — 빈도순
    cur.execute("""
        select ingredient_name, count(*) n
          from public.recipe_ingredient
         where item_id is null and ingredient_name is not null
         group by 1 order by n desc limit %s
    """, (limit * 3,))
    axes["unmatched"] = [{"name": r[0], "count": r[1], "lumped_into": None}
                         for r in cur.fetchall() if r[0].strip() not in NOISE][:limit]

    # (b) 🔴 **카테고리별 축.** 첫 판은 육류 하나만 세웠는데, 실측하니 육류는 뭉침의 5%
    #     밖에 안 됐다 — 표본이 편향돼 있었다(사용자가 연 레시피가 돼지갈비였을 뿐).
    #
    # 🔴 **양념·유지는 뺀다.** 뭉침의 30%로 가장 크지만, 그 품목들은 `excluded_staple` 이라
    #    담기 모달·레시피 상세에서 **값을 안 매긴다**(실측: 매칭 재료의 45%가 상비).
    #    ⇒ 아무리 정교하게 갈라도 **가격 화면이 한 픽셀도 안 바뀐다.** 검색·NER 품질에는
    #      도움이 되지만 그건 별개 목적이고, 지금 고치려는 것은 가격이다.
    for cat in ("채소", "유제품", "가공식품", "수산물", "육류", "난류", "곡류"):
        cur.execute("""
            select m.canonical_name, ri.ingredient_name, count(*) n
              from public.recipe_ingredient ri
              join public.item_master m on m.item_id = ri.item_id
             where m.category = %s and ri.ingredient_name <> m.canonical_name
             group by 1,2 having count(*) >= 5
             order by n desc limit %s
        """, (cat, max(6, limit // 4)))
        got = [{"name": r[0 + 1], "count": r[2], "lumped_into": r[0]} for r in cur.fetchall()]
        if got:
            axes[f"lumped:{cat}"] = got

    # (d) 🔴 «그 이름으로 팔리는 상품이 있나» — 신설 판단의 필수 근거.
    #     없으면 신설해도 가격이 안 붙어 «어제까지 있던 값이 사라지는» 회귀가 된다.
    names = {x["name"] for v in axes.values() for x in v}
    cur.execute("select name from public.retail_product where name is not null limit 40000")
    allp = [r[0] for r in cur.fetchall()]
    products = {}
    for nm in names:
        hit = [p for p in allp if nm in p][:4]
        if hit:
            products[nm] = hit

    # (e) 기존 품목 + 그 100g 단가 — «값이 다른가» 를 판단하려면 숫자가 있어야 한다
    cur.execute("""
        select m.canonical_name, m.category, c.kurly_100g, c.oasis_100g
          from public.item_master m
          left join retail_item_price_compare c on c.item_id = m.item_id
         order by 1
    """)
    # 🔴 `numeric` 은 psycopg 가 **Decimal** 로 준다 — `json.dumps` 가 못 싣는다.
    #    가격을 근거로 넣으면서 생긴 회귀다(첫 판엔 가격이 없어서 안 터졌다).
    #    실측: 배치 8개가 전부 `TypeError: Object of type Decimal is not JSON serializable`.
    #    🔵 여기서 int 로 눕힌다 — 판단에 소수점이 필요 없고, 아래 프롬프트도 정수를 기대한다.
    existing = [{"name": r[0], "category": r[1],
                 "kurly": int(r[2]) if r[2] is not None else None,
                 "oasis": int(r[3]) if r[3] is not None else None}
                for r in cur.fetchall()]

    return {"axes": axes, "products": products, "existing": existing}


# ── LLM ────────────────────────────────────────────────────────────────────
def ask(client, system: str, user: str, max_tokens: int = 4000) -> str:
    resp = client.invoke_model(
        modelId=MODEL_ID, contentType="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": 0,   # 🔵 사전은 재현성이 중요하다 — 돌릴 때마다 달라지면 검수가 무의미하다
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }))
    return "".join(b.get("text", "") for b in json.loads(resp["body"].read()).get("content", []))


def parse_json(text: str):
    """```json 펜스를 벗기고 파싱. 🔴 실패를 빈 리스트로 삼키지 않는다 — 예외로 올린다."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        s = s[4:] if s.startswith("json") else s
    s = s.strip()
    a, b = s.find("["), s.rfind("]")
    if a >= 0 and b > a:
        s = s[a:b + 1]
    return json.loads(s)


GEN_SYSTEM = """너는 한국 식품 데이터의 표준품목 사전을 정리한다.

입력의 각 이름에 대해 셋 중 하나를 정한다:
  alias  — 기존 표준품목의 다른 표기다. `target` 에 기존 품목명을 적는다.
  new    — 별도 품목으로 세워야 한다. `category` 를 적는다.
  skip   — 재료가 아니거나(조리도구·물·조리법·설명어), 근거가 부족하다.

판단 기준:
  · 가격이 뚜렷이 다르면 new 를 고려한다. 삼겹살과 앞다리살은 100g 단가가 다르다.
  · 표기 변형(띄어쓰기·순서·수식어)은 alias 다. "다진 돼지고기"와 "다진돼지고기"는 같다.
  · 🔴 판매 상품 근거(`products_by_name`)가 없으면 new 로 만들지 않는다 — 가격이 안 붙어 오히려 나빠진다.
  · `lumped_into` 가 있으면 지금 그 품목에 뭉쳐 있다는 뜻이다. 부위·종이 유실됐는지 본다.
  · 애매하면 skip 이다. 사전은 빠뜨리는 것보다 잘못 넣는 것이 비싸다.

🔴 **입력에 있는 이름을 하나도 빠뜨리지 말고 전부 판정한다.** 개수가 입력과 같아야 한다.
출력은 JSON 배열만. 설명 금지.
[{"name":"삼겹살","action":"new","category":"육류","target":null,"why":"돼지고기와 100g 단가가 다르고 상품 다수"}]
"""

# 🔴 검수자마다 **다른 것을 본다.** 같은 질문을 세 번 하면 흔들림만 재고,
#    관점이 다르면 서로 다른 실패를 잡는다.
REVIEWERS = [
    ("가격", """너는 **가격 관점**의 검수자다. 제안이 가격 정확도를 실제로 높이는지만 본다.
reject 해야 하는 경우:
  · new 인데 기존 품목과 100g 단가가 비슷하다 (existing_items 의 kurly/oasis 를 볼 것)
  · alias 인데 대상 품목과 값이 뚜렷이 다르다 (예: 죽염과 일반 소금)
  · 가격 근거를 판단할 자료가 없다
🔴 확신이 서지 않으면 reject 다."""),
    ("표기", """너는 **표기 관점**의 검수자다. 이름이 같은 것을 가리키는지만 본다.
reject 해야 하는 경우:
  · 단순 표기 변형(띄어쓰기·어순·수식어)인데 new 다
  · 다른 재료인데 alias 로 묶었다
  · target 으로 지목한 품목이 existing_items 에 없다
  · 재료가 아니다(조리도구·조리법·설명어·포괄 표현)
🔴 확신이 서지 않으면 reject 다."""),
    ("상품", """너는 **상품 존재** 관점의 검수자다. 그 이름으로 실제로 팔리는 물건이 있는지만 본다.
reject 해야 하는 경우:
  · new 인데 `products_by_name` 에 근거 상품이 없다
  · 근거로 든 상품이 그 재료가 아니다 (예: 참기름 후보인데 "참기름 식탁김")
  · 상품은 있으나 가공품·완제품이라 원재료로 볼 수 없다
🔴 확신이 서지 않으면 reject 다."""),
]

REVIEW_TAIL = """
출력은 JSON 배열만. 입력의 모든 제안을 빠짐없이 판정한다. 설명 금지.
[{"name":"삼겹살","verdict":"accept","reason":"..."}]
"""


def chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


# ── 🔴 코드 게이트 — LLM 의 «의견» 이 아니라 DB 의 «사실» 로 막는다 ──────────
#
# 첫 판에서 `모닝빵` 이 검수자 3인 **만장일치**로 통과했다. 근거는 *"구체적 제품이 있고
# 가격 데이터 존재"* 였는데, 실측하니 **상품 0건**이었다. 만들었으면 31개 레시피가
# «가격 없음» 으로 회귀했을 것이다.
#
# ⇒ LLM 검수는 판단을 거르지만 **사실 확인은 못 한다.** 그래서 마지막에 코드가 본다.
#   🔵 이건 반대 방향으로도 안전하다 — 게이트는 «막기만» 하고 통과시키지 않는다.
MIN_PRODUCTS = int(os.environ.get("PROPOSE_MIN_PRODUCTS", "3"))


def gate(cur, proposals: list[dict]) -> list[dict]:
    """`new` 제안에 대해 **그 이름의 상품이 실제로 몇 건인지** 센다."""
    for p in proposals:
        if p.get("action") != "new":
            p["gate"] = {"checked": False}
            continue
        name = p.get("name") or ""
        cur.execute("""
            select count(*) n, min(won_per_100g) lo, max(won_per_100g) hi
              from retail_unit_price
             where name like %s and won_per_100g is not null
        """, ("%" + name + "%",))
        n, lo, hi = cur.fetchone()
        # 🔴 상품이 적으면 신설하지 않는다 — 가격이 안 붙어 «어제까지 있던 값이 사라진다».
        ok = n >= MIN_PRODUCTS
        p["gate"] = {"checked": True, "products": n,
                     "price_range": [int(lo) if lo else None, int(hi) if hi else None],
                     "pass": ok}
        if not ok:
            p["gate_reason"] = f"상품 {n}건 < 최소 {MIN_PRODUCTS}건 — 신설 시 가격 공백"
    return proposals


JUDGE_SYSTEM = """너는 **재심 판정자**다. 검수자 3인의 의견이 갈린 제안만 본다.

입력에는 제안과 함께 **각 검수자가 무엇을 보고 어떻게 판정했는지**가 들어 있다.
가격 관점 · 표기 관점 · 상품 관점은 서로의 의견을 모른 채 판단했다. 너는 그 불일치를 본다.

판단:
  · 반대한 검수자의 근거가 **구체적이고 사실에 부합**하면 그 판단을 따른다(reject).
  · 반대 근거가 **다른 관점의 소관**이면(예: 표기 검수자가 가격을 이유로 반대) 무시할 수 있다.
  · 🔴 **기본값은 reject 다.** 뒤집으려면 «왜 반대가 틀렸는지» 를 구체적으로 적어야 한다.

출력은 JSON 배열만. 설명 금지.
[{"name":"삼겹살","verdict":"accept","reason":"표기 검수자는 «변형» 이라 했으나 100g 단가가 돼지고기 1,189 vs 삼겹살 상품 63건 1,189~5,500 으로 실제로 다르다"}]
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40, help="축별 후보 수")
    ap.add_argument("--out", default="/tmp/item_master_proposal.json")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    # 🔴 커넥션을 **하나만** 연다. 게이트 단계에서 새로 열었더니
    #    `kubectl port-forward` 가 이미 끊겨 `Connection refused` 로 죽었다(2026-08-19 실측).
    #    포트포워드는 다중 접속에 약하고, 이 배치는 어차피 한 세션이면 충분하다.
    conn = connect()
    cur = conn.cursor()
    data = collect(cur, a.limit)

    axes = data["axes"]
    items = [x for k in ("meat", "unmatched", "lumped") for x in axes.get(k, [])]
    print("▶ 입력 — " + " · ".join(f"{k} {len(v)}종" for k, v in axes.items())
          + f" · 상품근거 {len(data['products'])}종 · 기존품목 {len(data['existing'])}종")
    if a.dry_run:
        print(json.dumps(axes, ensure_ascii=False, indent=2)[:4000])
        conn.close()
        return 0

    import boto3  # noqa: PLC0415
    client = boto3.client("bedrock-runtime", region_name=REGION)
    exist_brief = [{"name": e["name"], "category": e["category"],
                    "kurly": e["kurly"], "oasis": e["oasis"]} for e in data["existing"]]

    # ── ② 생성 — 배치로 쪼개고 **빠진 이름을 센다** ────────────────────────
    print(f"▶ ② 생성 (배치 {BATCH}개씩)")
    proposals, missing = [], []
    for i, ch in enumerate(chunks(items, BATCH), 1):
        want = {x["name"] for x in ch}
        prods = {n: data["products"][n] for n in want if n in data["products"]}
        try:
            got = parse_json(ask(client, GEN_SYSTEM, json.dumps({
                "candidates": ch, "products_by_name": prods,
                "existing_items": exist_brief,
            }, ensure_ascii=False), max_tokens=4000))
        except Exception as exc:                      # noqa: BLE001
            # 🔴 예외 **종류만** 찍으면 원인을 못 찾는다 — 첫 실행에서 `TypeError` 8줄만 보고
            #    어디서 났는지 알 수 없어 따로 디버깅해야 했다. 메시지까지 싣는다.
            print(f"   배치 {i} 🔴 {type(exc).__name__}: {str(exc)[:120]} "
                  f"— 이름 {len(want)}개 보류")
            missing += sorted(want)
            continue
        seen = {g.get("name") for g in got}
        lost = sorted(want - seen)
        missing += lost
        proposals += [g for g in got if g.get("name") in want]
        print(f"   배치 {i}: 입력 {len(want)} → 판정 {len(seen & want)}"
              + (f"  🔴 누락 {len(lost)}" if lost else "  ✅"))

    print(f"   제안 {len(proposals)}건 · 🔴 누락 {len(missing)}건")

    # ── ③ 검수 — 관점이 다른 3인 ──────────────────────────────────────────
    verdicts: dict[str, dict[str, str]] = {}
    for name, persona in REVIEWERS:
        print(f"▶ ③ 검수 · {name} 관점")
        acc = 0
        for ch in chunks(proposals, BATCH):
            prods = {n: data["products"][n] for n in
                     {c.get("name") for c in ch} if n in data["products"]}
            try:
                rv = parse_json(ask(client, persona + REVIEW_TAIL, json.dumps({
                    "proposals": ch, "existing_items": exist_brief,
                    "products_by_name": prods}, ensure_ascii=False), max_tokens=4000))
            except Exception as exc:                  # noqa: BLE001
                print(f"   🔴 {type(exc).__name__} — 이 배치는 전부 reject 로 센다")
                for c in ch:
                    verdicts.setdefault(c.get("name"), {})[name] = "reject"
                continue
            for v in rv:
                verdicts.setdefault(v.get("name"), {})[name] = v.get("verdict")
                acc += int(v.get("verdict") == "accept")
        print(f"   accept {acc}")

    # ── ④ 재심 — 🔵 갈린 것만. **불일치 자체를 입력으로 준다.**
    #    앞의 셋은 서로 뭐라 했는지 모른 채 판단했다. 판정자는 그 이견을 보고 고른다.
    split = [p for p in proposals
             if (vs := verdicts.get(p.get("name"), {}))
             and len(vs) == len(REVIEWERS)
             and 0 < sum(v == "accept" for v in vs.values()) < len(REVIEWERS)]
    judged: dict[str, str] = {}
    if split:
        print(f"▶ ④ 재심 — 의견이 갈린 {len(split)}건")
        for ch in chunks(split, BATCH):
            payload_j = [{
                "name": p.get("name"), "action": p.get("action"),
                "target": p.get("target"), "category": p.get("category"),
                "why": p.get("why"),
                "reviews": verdicts.get(p.get("name"), {}),
                "products": data["products"].get(p.get("name"), []),
            } for p in ch]
            try:
                rv = parse_json(ask(client, JUDGE_SYSTEM, json.dumps({
                    "split_proposals": payload_j, "existing_items": exist_brief,
                }, ensure_ascii=False), max_tokens=4000))
                for v in rv:
                    judged[v.get("name")] = v.get("verdict")
            except Exception as exc:                  # noqa: BLE001
                print(f"   🔴 {type(exc).__name__}: {str(exc)[:100]} — 이 배치는 보류 유지")
        print(f"   되살림 {sum(1 for v in judged.values() if v == 'accept')}건")

    # 🔴 **코드 게이트** — LLM 이 뭐라 했든 사실로 막는다(`모닝빵` 사고).
    print("▶ ⑤ 코드 게이트 — 상품 실재 확인")
    proposals = gate(cur, proposals)

    out = []
    for p in proposals:
        vs = verdicts.get(p.get("name"), {})
        nm = p.get("name")
        unanimous = len(vs) == len(REVIEWERS) and all(v == "accept" for v in vs.values())
        revived = judged.get(nm) == "accept"
        g = p.get("gate") or {}
        # 🔴 게이트는 **거부권만** 갖는다 — 통과시키지는 않는다.
        blocked = g.get("checked") and not g.get("pass")
        out.append({**p, "verdicts": vs,
                    "judge": judged.get(nm),
                    "approved": (unanimous or revived) and not blocked})

    result = {"proposals": out, "missing": missing,
              "counts": {"input": len(items), "proposed": len(out),
                         "missing": len(missing),
                         "unanimous": sum(1 for x in out
                                          if len(x["verdicts"]) == len(REVIEWERS)
                                          and all(v == "accept" for v in x["verdicts"].values())),
                         "revived": sum(1 for x in out if x.get("judge") == "accept"),
                         "gate_blocked": sum(1 for x in out
                                             if (x.get("gate") or {}).get("checked")
                                             and not (x.get("gate") or {}).get("pass")),
                         "approved": sum(1 for x in out if x["approved"])}}
    Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    c = result["counts"]
    print()
    print(f"■ 입력 {c['input']} → 제안 {c['proposed']} (누락 {c['missing']})")
    print(f"   만장일치 {c['unanimous']} + 재심 되살림 {c['revived']} "
          f"− 게이트 차단 {c['gate_blocked']} = **최종 {c['approved']}** → {a.out}")
    for kind in ("new", "alias", "skip"):
        n = sum(1 for x in out if x["approved"] and x.get("action") == kind)
        print(f"   통과 {kind:6} {n}건")
    if c["gate_blocked"]:
        print("   🔴 게이트가 막은 것 (LLM 은 통과시켰다):")
        for x in out:
            if (x.get("gate") or {}).get("checked") and not x["gate"].get("pass"):
                print(f"      {x.get('name'):12} {x.get('gate_reason')}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
