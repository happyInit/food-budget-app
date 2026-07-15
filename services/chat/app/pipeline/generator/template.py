"""TemplateGenerator — 검색 결과를 템플릿 문장으로 렌더. 0원·승인 불필요
(외부 API 호출 0 → AGENTS.md 절대제약 무관, docs/chat-assistant-ai.md §3).

생성이 아니라 검색 결과를 기계적으로 문장에 대입하는 것뿐이라 환각 여지가 없다
— 출력 대조 가드레일(guardrails.py)이 템플릿 모드에선 구조적으로 불필요.
"""
from __future__ import annotations

from app.models import ActionButton, BasisTag, ExtractedQuery
from app.pipeline.context import AssembledContext
from app.pipeline.generator.base import GeneratedAnswer, Generator
from app.pipeline.links import mankae_url, youtube_search_url
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
        # 레시피 3티어 폴백: ES 색인(고품질) → PG-only 10K(타 서비스 링크) → 없음(유튜브)
        tier1 = self._recommend(ctx, question)          # 티어1: ES 레시피 + 관련성 게이트
        if tier1:
            return tier1
        tier2 = self._external_recipe(ctx, question)     # 티어2: PG-only 10K → 만개 링크
        if tier2:
            return tier2
        return self._youtube_fallback(question)          # 티어3: 유튜브 검색 + 기능 소개

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

    def _recommend(self, ctx: AssembledContext, question: ExtractedQuery) -> GeneratedAnswer | None:
        """티어1: ES 색인 레시피 + 관련성 게이트. 게이트 통과 없으면 None(→ 티어2로)."""
        if not ctx.recipes:
            return None
        words = _meaningful_words(question.raw_text)
        # ES는 관련성 임계값 없이 느슨하게 매칭하므로(§search 알려진 한계), 여기서
        # 질문의 내용어가 레시피명에 실제로 있는지 substring 확인 — 없으면 근거 없는 답으로
        # 보고 미응답 처리. (iter4: 경계매칭은 복합 요리명 "매콤돼지갈비찜"⊃"갈비찜"을 놓쳐
        # recall을 깨고, startswith 방향이 "인기있는"→"인기" 오매칭을 냄 → substring으로 복귀.
        # 형태소 경계 오매칭[주식⊂나주식]은 오프토픽 명사 불용어가 선제 제거해 안전.)
        top = [r for r in ctx.recipes[:3] if any(w in r["name"] for w in words)]
        if not top:
            return None
        header = "이런 레시피는 어때요?"
        if question.budget_won:
            header += f" (예산 {question.budget_won:,}원 참고)"
        lines = [header] + [f"- {r['name']}" for r in top]
        basis = [BasisTag(type="recipe_match", detail=r["name"]) for r in top]
        return GeneratedAnswer(text="\n".join(lines), basis=basis)

    def _external_recipe(self, ctx: AssembledContext, question: ExtractedQuery) -> GeneratedAnswer | None:
        """티어2: ES엔 없지만 PG에 있는 10K(만개) 레시피 → '타 서비스에서 찾음' + 링크.

        근거 type=external_recipe(≠recipe_match)라 GeminiGenerator가 refine을 자동 우회 → 0원,
        링크·멘트를 LLM이 건드리지 않음. 티어1이 실패한 뒤라 이 매칭은 사실상 'ES-미포함'.
        """
        words = _meaningful_words(question.raw_text)
        for r in ctx.pg_recipes:
            if r.get("source") != "10K" or not r.get("src_recipe_id"):
                continue                                  # 10K(만개)만 링크(결정사항)
            if not any(w in r["name"] for w in words):    # 티어1과 동일 관련성 게이트
                continue
            url = mankae_url(r["src_recipe_id"])
            text = (f"우리 서비스엔 아직 없지만, 다른 레시피 서비스에서 '{r['name']}' 레시피를 찾았어요! "
                    f"확인해보시겠어요?\n{url}")
            action = ActionButton(action="open_url", label=f"'{r['name']}' 레시피 보러가기", url=url)
            basis = [BasisTag(type="external_recipe", detail=r["name"])]
            return GeneratedAnswer(text=text, basis=basis, actions=[action])
        return None

    def _youtube_fallback(self, question: ExtractedQuery) -> GeneratedAnswer:
        """티어3: 어디에도 없음 → 유튜브 검색 링크 + '영상→레시피 추출' 기능 소개.

        basis 비움 → unanswered=True(정직) + GeminiGenerator refine 우회(0원). 유튜브 실검색 안 함.
        """
        words = _meaningful_words(question.raw_text)
        dish = " ".join(words) if words else question.raw_text.strip()
        url = youtube_search_url(dish)
        text = (f"'{dish}' 레시피는 아직 우리 서비스에 없어요. 유튜브에서 찾아보실 수 있어요:\n{url}\n"
                "마음에 드는 영상 링크를 넣어주시면, 영상에서 재료·조리법을 자동으로 뽑아 "
                "레시피로 만들어드리는 기능도 준비돼 있어요!")
        action = ActionButton(action="open_url", label="유튜브에서 검색하기", url=url)
        return GeneratedAnswer(text=text, basis=[], actions=[action])
