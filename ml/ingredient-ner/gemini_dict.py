"""④-d Gemini 오프라인 사전 증강 — 코퍼스에서 '사전 밖 재료'를 1회 추출해 dict_gemini.txt 생성.

⚠️ **오프라인 1회성.** 런타임(챗봇)·주기 호출 없음. Gemini는 여기서 사전을 만들 때만 부르고,
그다음부턴 무료 CRF가 그 사전으로 학습·서빙한다. moat·비용 그대로.
자기학습(self_train.py)이 0개였던 이유(CRF가 사전 밖 재료를 못 봄)를 Gemini가 보완 =
우리가 "없다"던 외부 식품 사전 역할.

거버넌스: Gemini 새 용도(챗봇 다듬기 외). 오프라인·1회·소액이나 팀 인지 대상(AGENTS.md).

━━ 재실행 기준(수동, 자동 반복 아님) — "코퍼스가 크게 늘어서"의 명시적 정의 ━━
아래 중 하나라도 충족할 때만 다시 실행한다(dict_gemini.meta.json의 built_n_texts와 비교):
  (1) 학습 코퍼스(source != '10K', ner_status RAW/LABELED) 텍스트 수가 **직전 구축 대비 ≥ 20% 증가**
  (2) **새 학습 소스 추가**(예: COOKRCP01 실키 전량 적재, 신규 공공 레시피 소스)
  (3) 신규 데이터에서 CRF recall이 gold 대비 **뚜렷이 저하**(≥ 3%p)
그 외에는 재호출하지 않는다(이미 만든 dict_gemini.txt 재사용).

사용: python gemini_dict.py [--limit N] [--batch B]   (파일럿: --limit 100)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from weak_label import _DIR, build_dict, dict_paths

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / "services" / "chat" / ".env")   # GEMINI_API_KEY
_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
_HANGUL = re.compile(r"^[가-힣][가-힣 ]{1,7}$")
# Flash-Lite 근사 요율(시점 변동, 확인 권장)
_IN_RATE, _OUT_RATE, _KRW = 0.10 / 1e6, 0.40 / 1e6, 1380

_SYSTEM = (
    "너는 한국 레시피 재료명 추출기다. 주어진 각 재료 텍스트들에서 '재료명'만 뽑아라.\n"
    "- 수량·단위(30g, 1개, 약간, 적당량)와 조리표현·섹션명(양념/소스/주재료/고명 등)은 제외.\n"
    "- 재료명은 텍스트에 나온 형태 그대로(정규화·번역·표준화 금지).\n"
    "- 출력: 재료명만 중복 없이 한 줄에 하나. 설명·번호·기타 텍스트 없이 목록만."
)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0=전체, 파일럿은 100")
    ap.add_argument("--batch", type=int, default=15)
    args = ap.parse_args()

    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY 없음 — services/chat/.env 확인")
    client = genai.Client(api_key=key)

    rows = [json.loads(l) for l in (_DIR / "corpus.jsonl").read_text(encoding="utf-8").splitlines()]
    texts = [r["text"] for r in rows if r["text"].strip()]
    if args.limit:
        texts = texts[: args.limit]

    multi, single = build_dict(*dict_paths())
    known = {m.replace(" ", "") for m in multi} | single

    found: set[str] = set()
    tin = tout = 0
    for i in range(0, len(texts), args.batch):
        chunk = texts[i : i + args.batch]
        body = "\n".join(f"[{j+1}] {t}" for j, t in enumerate(chunk))
        resp = await client.aio.models.generate_content(
            model=_MODEL, contents=body,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM, max_output_tokens=1024, temperature=0.0),
        )
        u = resp.usage_metadata
        tin += u.prompt_token_count or 0
        tout += u.candidates_token_count or 0
        for line in (resp.text or "").splitlines():
            w = line.strip().lstrip("-·*0123456789.[] ").strip()
            if _HANGUL.match(w):
                found.add(w)

    new = sorted(w for w in found if w.replace(" ", "") not in known)
    (_DIR / "dict_gemini.txt").write_text("\n".join(new), encoding="utf-8")

    usd = tin * _IN_RATE + tout * _OUT_RATE
    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "model": _MODEL, "pilot_limit": args.limit or "full",
        "processed_texts": len(texts), "batch": args.batch,
        "n_calls": (len(texts) + args.batch - 1) // args.batch,
        "tokens_in": tin, "tokens_out": tout,
        "cost_usd": round(usd, 5), "cost_krw": round(usd * _KRW, 1),
        "n_new_dict_terms": len(new),
        "rerun_rule": "corpus +20% / new source / recall drop ≥3%p (수동)",
        "built_n_texts_reference": len(rows),
    }
    (_DIR / "dict_gemini.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"처리 {len(texts)} 텍스트 · {meta['n_calls']} 호출")
    print(f"토큰 in {tin} / out {tout} → 비용 ${usd:.5f} ≈ {usd*_KRW:.1f}원")
    print(f"신규 사전어 {len(new)}개 → dict_gemini.txt")
    print("  예:", new[:25])


if __name__ == "__main__":
    asyncio.run(main())
