"""TemplateGenerator — 검색 결과를 템플릿 문장으로 렌더. 0원·승인 불필요
(외부 API 호출 0 → AGENTS.md 절대제약 무관, docs/chat-assistant-ai.md §3).

생성이 아니라 검색 결과를 기계적으로 문장에 대입하는 것뿐이라 환각 여지가 없다
— 출력 대조 가드레일(guardrails.py)이 템플릿 모드에선 구조적으로 불필요.
"""
from __future__ import annotations

from app.models import BasisTag, ExtractedQuery
from app.pipeline.context import AssembledContext
from app.pipeline.generator.base import GeneratedAnswer, Generator


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
        top = ctx.recipes[:3]
        header = "이런 레시피는 어때요?"
        if question.budget_won:
            header += f" (예산 {question.budget_won:,}원 참고)"
        lines = [header] + [f"- {r['name']}" for r in top]
        basis = [BasisTag(type="recipe_match", detail=r["name"]) for r in top]
        return GeneratedAnswer(text="\n".join(lines), basis=basis)
