"""TemplateGenerator — 검색 결과를 템플릿 문장으로 렌더. 0원·승인 불필요
(외부 API 호출 0 → AGENTS.md 절대제약 무관, docs/chat-assistant-ai.md §3).

생성이 아니라 검색 결과를 기계적으로 문장에 대입하는 것뿐이라 환각 여지가 없다
— 출력 대조 가드레일(guardrails.py)이 템플릿 모드에선 구조적으로 불필요.
"""
from __future__ import annotations

from app.models import BasisTag, ExtractedQuery
from app.pipeline.context import AssembledContext
from app.pipeline.generator.base import GeneratedAnswer, Generator
from app.pipeline.text_relevance import meaningful_words as _meaningful_words


class TemplateGenerator(Generator):
    async def generate(self, question: ExtractedQuery, ctx: AssembledContext) -> GeneratedAnswer:
        if question.intent == "price_lookup" and ctx.item_ids:
            answer = self._price_lookup(ctx)
            if answer:
                return answer
        if question.intent == "nutrition" and ctx.item_ids:
            answer = self._nutrition(ctx)
            if answer:
                return answer
        if ctx.recipes:
            return self._recommend(ctx, question)
        return GeneratedAnswer(text="모르겠어요 — 관련 정보를 찾지 못했습니다.")

    def _price_lookup(self, ctx: AssembledContext) -> GeneratedAnswer | None:
        lines: list[str] = []
        basis: list[BasisTag] = []
        for item_id in ctx.item_ids:
            rows = ctx.prices.get(item_id, [])
            parts = [f"{r['source']} {int(r['price']):,}원" for r in rows if r.get("price") is not None]
            if not parts:
                continue
            lines.append(" · ".join(parts))
            for r in rows:
                basis.append(
                    BasisTag(type="price_snapshot", item_id=item_id, source=r["source"], crawled_at=r.get("crawled_at"))
                )
        if not lines:
            return None
        return GeneratedAnswer(text="\n".join(lines), basis=basis)

    def _nutrition(self, ctx: AssembledContext) -> GeneratedAnswer | None:
        lines: list[str] = []
        basis: list[BasisTag] = []
        for item_id in ctx.item_ids:
            n = ctx.nutrition.get(item_id)
            if not n:
                continue
            lines.append(
                f"{n['food_name']}: {n['kcal']}kcal, 탄수화물 {n['carb_g']}g · 단백질 {n['protein_g']}g · 지방 {n['fat_g']}g"
            )
            basis.append(BasisTag(type="nutrition", item_id=item_id, detail=n["food_name"]))
        if not lines:
            return None
        return GeneratedAnswer(text="\n".join(lines), basis=basis)

    def _recommend(self, ctx: AssembledContext, question: ExtractedQuery) -> GeneratedAnswer:
        words = _meaningful_words(question.raw_text)
        # ES는 관련성 임계값 없이 느슨하게 매칭하므로(§search 알려진 한계), 여기서
        # 질문의 내용어가 레시피명에 실제로 있는지 substring 확인 — 없으면 근거 없는 답으로
        # 보고 미응답 처리. (iter4: 경계매칭은 복합 요리명 "매콤돼지갈비찜"⊃"갈비찜"을 놓쳐
        # recall을 깨고, startswith 방향이 "인기있는"→"인기" 오매칭을 냄 → substring으로 복귀.
        # 형태소 경계 오매칭[주식⊂나주식]은 오프토픽 명사 불용어가 선제 제거해 안전.)
        top = [r for r in ctx.recipes[:3] if any(w in r["name"] for w in words)]
        if not top:
            return GeneratedAnswer(text="모르겠어요 — 관련 레시피를 찾지 못했습니다.")
        header = "이런 레시피는 어때요?"
        if question.budget_won:
            header += f" (예산 {question.budget_won:,}원 참고)"
        lines = [header] + [f"- {r['name']}" for r in top]
        basis = [BasisTag(type="recipe_match", detail=r["name"]) for r in top]
        return GeneratedAnswer(text="\n".join(lines), basis=basis)
