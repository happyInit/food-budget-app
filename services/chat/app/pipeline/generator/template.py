"""TemplateGenerator — 검색 결과를 템플릿 문장으로 렌더. 0원·승인 불필요
(외부 API 호출 0 → AGENTS.md 절대제약 무관, docs/chat-assistant-ai.md §3).

생성이 아니라 검색 결과를 기계적으로 문장에 대입하는 것뿐이라 환각 여지가 없다
— 출력 대조 가드레일(guardrails.py)이 템플릿 모드에선 구조적으로 불필요.
"""
from __future__ import annotations

import re

from app.models import BasisTag, ExtractedQuery
from app.pipeline.context import AssembledContext
from app.pipeline.generator.base import GeneratedAnswer, Generator
from app.pipeline.text_relevance import meaningful_words as _meaningful_words


def _as_int(x) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


# 소스 코드 → 사용자용 한글 매장명(가독성). 미지 소스는 원문 그대로.
_SOURCE_KR = {"kurly": "컬리마켓", "oasis": "오아시스마켓"}

# 상품명에서 판매용량 추출(예 "국내산 삼겹살 500g" → "500g"). 첫 매치만.
_VOLUME_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:kg|g|ml|리터|l|개입|개입수|입|팩|봉지|봉|구|미|매|장|병|캔|포|과|낱개|호)",
    re.IGNORECASE,
)


def _volume(name) -> str | None:
    if not name:
        return None
    m = _VOLUME_RE.search(str(name))
    return m.group(0).replace(" ", "") if m else None


class TemplateGenerator(Generator):
    async def generate(self, question: ExtractedQuery, ctx: AssembledContext) -> GeneratedAnswer:
        names = dict(zip(question.item_ids, question.item_names))   # item_id→표준품목명(라벨용)
        if question.intent == "price_lookup" and ctx.item_ids:
            answer = self._price_lookup(ctx, names)
            if answer:
                return answer
        if question.intent == "nutrition" and ctx.item_ids:
            answer = self._nutrition(ctx, names)
            if answer:
                return answer
        if ctx.recipes:
            answer = self._recommend(ctx, question)
            if answer.basis:
                return answer
        # 레시피 0건이지만 질문이 표준 품목으로 정규화됐다면(예: "소갈비"→"갈비") 제안형 응답.
        # 자동 치환은 안 함(육류 구분 이슈, item_master 개선 대기) — 유저에게 표준명으로 재검색을 제안만.
        suggest = self._suggest(question)
        if suggest:
            return suggest
        return GeneratedAnswer(text="모르겠어요 — 관련 정보를 찾지 못했습니다.")

    def _suggest(self, question: ExtractedQuery) -> GeneratedAnswer | None:
        # 질문이 이미 쓴 단어와 다른 표준 품목명만 제안(예: "소갈비"≠"갈비"). canonical은 gazetteer에서
        # 오므로 item_master가 육류 구분을 갖추면 제안 문구도 자동 갱신(서비스 재기동 시 반영).
        typed = set(_meaningful_words(question.raw_text))
        cands = list(dict.fromkeys(n for n in question.item_names if n and n not in typed))
        if not cands:
            return None
        names = "·".join(f"'{n}'" for n in cands[:2])
        return GeneratedAnswer(
            text=f"찾으시는 레시피를 바로 찾지 못했어요. 대신 {names} 요리를 찾아드릴까요?"
        )

    def _price_lookup(self, ctx: AssembledContext, names: dict[int, str] | None = None) -> GeneratedAnswer | None:
        names = names or {}
        blocks: list[str] = []
        basis: list[BasisTag] = []
        for item_id in ctx.item_ids:
            rows = [r for r in ctx.prices.get(item_id, []) if r.get("price") is not None]
            if not rows:
                continue
            label = names.get(item_id) or "해당 상품"
            # 헤더 — 용량은 상품명에서 추출(소스마다 다를 수 있어 대표 1개만 헤더에 표기)
            head_vol = next((v for r in rows if (v := _volume(r.get("name")))), None)
            header = f"{label}{f' ({head_vol})' if head_vol else ''} 가격은?"
            # 소스별 줄 — 한글 매장명 + 용량(다르면)
            source_lines = []
            for r in rows:
                src = _SOURCE_KR.get(r["source"], r["source"])
                vol = _volume(r.get("name"))
                vol_str = f" ({vol})" if vol and vol != head_vol else ""
                source_lines.append(f"· {src} 기준 {int(r['price']):,}원{vol_str}")
                basis.append(
                    BasisTag(type="price_snapshot", item_id=item_id, source=r["source"], crawled_at=r.get("crawled_at"))
                )
            block = header + "\n" + "\n".join(source_lines)
            # 최저가 안내(값이 다를 때만)
            if len(rows) >= 2 and len({int(r["price"]) for r in rows}) > 1:
                cheapest = min(rows, key=lambda r: int(r["price"]))
                block += f"\n현재 {_SOURCE_KR.get(cheapest['source'], cheapest['source'])}이 가장 저렴해요!"
            blocks.append(block)
        if not blocks:
            return None
        return GeneratedAnswer(text="\n\n".join(blocks), basis=basis)

    def _nutrition(self, ctx: AssembledContext, names: dict[int, str] | None = None) -> GeneratedAnswer | None:
        names = names or {}
        lines: list[str] = []
        basis: list[BasisTag] = []
        for item_id in ctx.item_ids:
            n = ctx.nutrition.get(item_id)
            if not n:
                continue
            label = names.get(item_id) or n["food_name"]    # 표준품목명 우선, 없으면 영양DB명
            lines.append(
                f"{label} 영양성분은 {n['kcal']}kcal, 탄수화물 {n['carb_g']}g · "
                f"단백질 {n['protein_g']}g · 지방 {n['fat_g']}g이에요."
            )
            basis.append(BasisTag(type="nutrition", item_id=item_id, detail=n["food_name"]))
        if not lines:
            return None
        return GeneratedAnswer(text="\n".join(lines), basis=basis)

    def _recommend(self, ctx: AssembledContext, question: ExtractedQuery) -> GeneratedAnswer:
        # 관련성 필터 — ES는 임계값 없이 느슨히 매칭하므로(§search 한계) 여기서 재확인.
        #  · 품목이 추출됐으면(재료 질문/팔로우업) → 레시피의 ingredient_item_ids와 **구조 매칭**.
        #    표준명("돼지고기")≠표면형("삼겹살") 차이나 대화필러("다른 추천")에 안 흔들림.
        #  · 품목이 없으면(요리명 질문 "된장찌개") → 이름 substring(raw 내용어) 폴백 = 기존 동작.
        if question.item_ids:
            want = set(question.item_ids)
            top = [
                r for r in ctx.recipes[:5]
                if want & {i for x in (r.get("ingredient_item_ids") or []) if (i := _as_int(x)) is not None}
            ][:3]
        else:
            words = _meaningful_words(question.raw_text)
            top = [r for r in ctx.recipes[:3] if any(w in r["name"] for w in words)]
        if not top:
            return GeneratedAnswer(text="모르겠어요 — 관련 레시피를 찾지 못했습니다.")
        recipe_names = ", ".join(f"'{r['name']}'" for r in top)
        text = f"{recipe_names} 같은 요리는 어때요?"
        if question.budget_won:
            text += f" (예산 {question.budget_won:,}원 참고)"
        basis = [BasisTag(type="recipe_match", detail=r["name"]) for r in top]
        return GeneratedAnswer(text=text, basis=basis)
