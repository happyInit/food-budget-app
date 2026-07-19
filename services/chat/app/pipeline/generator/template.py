"""TemplateGenerator — 검색 결과를 템플릿 문장으로 렌더. 0원·승인 불필요
(외부 API 호출 0 → AGENTS.md 절대제약 무관, docs/chat-assistant-ai.md §3).

생성이 아니라 검색 결과를 기계적으로 문장에 대입하는 것뿐이라 환각 여지가 없다
— 출력 대조 가드레일(guardrails.py)이 템플릿 모드에선 구조적으로 불필요.
"""
from __future__ import annotations

import re

from app.models import ActionButton, BasisTag, ExtractedQuery
from app.pipeline.context import AssembledContext
from app.pipeline.generator.base import GeneratedAnswer, Generator
from app.pipeline.links import mankae_url
from app.pipeline.text_relevance import meaningful_words as _meaningful_words


def _as_int(x) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _recipe_ings(recipe: dict) -> set[int]:
    """레시피의 재료 item_id 집합(구조 매칭·비선호 제외용)."""
    return {i for x in (recipe.get("ingredient_item_ids") or []) if (i := _as_int(x)) is not None}


# 소스 코드 → 사용자용 한글 매장명(가독성). 미지 소스는 원문 그대로.
_SOURCE_KR = {"kurly": "컬리마켓", "oasis": "오아시스마켓"}

# 상품명에서 판매용량 추출(예 "국내산 삼겹살 500g" → "500g"). 첫 매치만.
_VOLUME_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:kg|g|ml|리터|l|개입|개입수|입|팩|봉지|봉|구|미|매|장|병|캔|포|과|낱개|호)",
    re.IGNORECASE,
)


# 상비 재료(양념·조미료) — 집에 보통 있는 것. 재료비 합산에서 제외(팀 결정).
_STAPLES = frozenset({
    "소금", "후추", "후춧가루", "흰후추", "통후추", "설탕", "백설탕", "황설탕", "흑설탕",
    "간장", "국간장", "진간장", "양조간장", "조선간장", "고추장", "된장", "쌈장", "춘장",
    "고춧가루", "식용유", "카놀라유", "올리브유", "포도씨유", "콩기름", "참기름", "들기름",
    "마늘", "다진마늘", "생강", "다진생강", "식초", "사과식초", "발사믹식초", "맛술", "미림", "미린", "청주",
    "올리고당", "물엿", "조청", "꿀", "깨", "통깨", "참깨", "깨소금", "케첩", "마요네즈",
    "굴소스", "액젓", "멸치액젓", "까나리액젓", "새우젓", "다시다", "미원", "치킨스톡", "물",
    "김치",   # 대부분 집에 상비(팀 결정) — 가격 매기기 애매
})


def _is_staple(name: str | None) -> bool:
    return (name or "").replace(" ", "") in _STAPLES


def _volume(name) -> str | None:
    if not name:
        return None
    m = _VOLUME_RE.search(str(name))
    return m.group(0).replace(" ", "") if m else None


class TemplateGenerator(Generator):
    async def generate(self, question: ExtractedQuery, ctx: AssembledContext) -> GeneratedAnswer:
        names = dict(zip(question.item_ids, question.item_names))   # item_id→표준품목명(라벨용)
        if question.intent == "recipe_cost":
            return self._recipe_cost(question, ctx)
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
        # 티어2 폴백 — ES엔 없지만 PG에 10K(만개) 레시피가 있으면 '타 서비스 링크'로 안내.
        #   근거 type=external_recipe(≠recipe_match) → GeminiGenerator refine 자동 우회(0원).
        if question.intent in ("recommend", "unknown"):
            external = self._external_recipe(ctx, question)
            if external:
                return external
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
                op = r.get("original_price")
                disc = ""
                if op and op > r["price"]:
                    rate = r.get("discount_rate")
                    disc = f" (정가 {int(op):,}원{f' · {int(rate)}%↓' if rate else ''})"
                source_lines.append(f"· {src} 기준 {int(r['price']):,}원{vol_str}{disc}")
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
            block = [f"{label} 영양성분은?"]
            if n.get("kcal") is not None:
                block.append(f"· 열량 {n['kcal']:g}kcal")
            macros = [f"{nm} {n[k]:g}g" for k, nm in
                      (("carb_g", "탄수화물"), ("protein_g", "단백질"), ("fat_g", "지방")) if n.get(k) is not None]
            if macros:
                block.append("· " + " · ".join(macros))
            extra = []
            if n.get("sugar_g") is not None:
                extra.append(f"당류 {n['sugar_g']:g}g")
            if n.get("sodium_mg") is not None:
                extra.append(f"나트륨 {int(n['sodium_mg']):,}mg")
            if extra:
                block.append("· " + " · ".join(extra))
            lines.append("\n".join(block))
            basis.append(BasisTag(type="nutrition", item_id=item_id, detail=n["food_name"]))
        if not lines:
            return None
        return GeneratedAnswer(text="\n\n".join(lines), basis=basis)

    def _recipe_cost(self, question: ExtractedQuery, ctx: AssembledContext) -> GeneratedAnswer:
        """레시피 재료비 = 재료별 최저가 합산(§식비 킬러 기능). 가격 없는 재료·수량은 정직 표기."""
        name = question.recipe_name or "이 요리"
        if not ctx.item_ids:
            return GeneratedAnswer(text="어떤 요리의 재료비가 궁금하세요? 먼저 요리를 추천받아 보세요!")
        names = dict(zip(question.item_ids, question.item_names))
        items: list[tuple[str, int, bool]] = []   # (재료명, 비용, 정확여부)
        total = 0
        n_exact = 0
        basis: list[BasisTag] = []
        for item_id in ctx.item_ids:
            nm = names.get(item_id)
            if _is_staple(nm):
                continue               # 소금·후추·소스류·김치 등 상비 재료 제외(팀 결정)
            uc = question.unit_costs.get(item_id)
            if uc is not None:         # 용량×단가 = 정확한 끼당 비용(무게 표기 재료)
                total += uc
                n_exact += 1
                items.append((nm or "재료", uc, True))
                basis.append(BasisTag(type="price_snapshot", item_id=item_id))
            else:                      # 폴백 — 팩 최저가(개수·비정형 용량)
                rows = [r for r in ctx.prices.get(item_id, []) if r.get("price") is not None]
                if not rows:
                    continue
                cheapest = min(rows, key=lambda r: int(r["price"]))
                total += int(cheapest["price"])
                items.append((nm or "재료", int(cheapest["price"]), False))
                basis.append(BasisTag(type="price_snapshot", item_id=item_id,
                                      source=cheapest["source"], crawled_at=cheapest.get("crawled_at")))
        if not items:
            return GeneratedAnswer(text=f"'{name}'의 재료 가격 정보를 아직 찾지 못했어요.")
        items.sort(key=lambda x: -x[1])   # 비싼 순
        serv = f" ({question.servings}인분)" if question.servings else ""
        lines = [f"'{name}'{serv} 재료비는 약 {total:,}원이에요."]
        lines += [f"· {nm} {c:,}원{'' if ex else ' (팩값)'}" for nm, c, ex in items[:5]]
        if len(items) > 5:
            lines.append(f"· 외 {len(items) - 5}개")
        n_fb = len(items) - n_exact
        note = f"(재료 {len(items)}개 · 소금·양념 등 상비 제외"
        if n_exact and n_fb:
            note += f" · {n_exact}개 레시피 용량 반영, {n_fb}개 팩값"
        elif n_exact:
            note += " · 레시피 용량 반영"
        else:
            note += " · 팩 최저가 기준"
        lines.append(note + ")")
        return GeneratedAnswer(text="\n".join(lines), basis=basis)

    def _external_recipe(self, ctx: AssembledContext, question: ExtractedQuery) -> GeneratedAnswer | None:
        """티어2: ES엔 없지만 PG에 있는 10K(만개) 레시피 → '타 서비스에서 찾음' + 링크.

        근거 type=external_recipe(≠recipe_match)라 GeminiGenerator가 refine을 자동 우회 → 0원,
        링크·멘트를 LLM이 건드리지 않음. 티어1 실패 뒤라 이 매칭은 사실상 'ES-미포함' 레시피.
        """
        words = _meaningful_words(question.raw_text)
        for r in ctx.pg_recipes:
            if r.get("source") != "10K" or not r.get("src_recipe_id"):
                continue                                  # 10K(만개)만 링크(결정사항)
            if not any(w in r["name"] for w in words):    # 티어1과 동일 관련성 게이트
                continue
            url = mankae_url(r["src_recipe_id"])
            # URL은 텍스트에 넣지 않는다 — 아래 open_url 액션(버튼/카드)으로만 노출(raw URL 노출 방지).
            text = (f"우리 서비스엔 아직 없지만, 다른 레시피 서비스에서 '{r['name']}' 레시피를 찾았어요! "
                    f"아래 버튼으로 확인해보세요.")
            action = ActionButton(action="open_url", label=f"'{r['name']}' 레시피 보러가기", url=url)
            basis = [BasisTag(type="external_recipe", detail=r["name"])]
            return GeneratedAnswer(text=text, basis=basis, actions=[action])
        return None

    def _recommend(self, ctx: AssembledContext, question: ExtractedQuery) -> GeneratedAnswer:
        # 관련성 필터 — ES는 임계값 없이 느슨히 매칭하므로(§search 한계) 여기서 재확인.
        #  · 품목이 추출됐으면(재료 질문/팔로우업) → 레시피의 ingredient_item_ids와 **구조 매칭**.
        #    표준명("돼지고기")≠표면형("삼겹살") 차이나 대화필러("다른 추천")에 안 흔들림.
        #  · 품목이 없으면(요리명 질문 "된장찌개") → 이름 substring(raw 내용어) 폴백 = 기존 동작.
        # 세션 개인화 — 비선호 재료가 든 레시피 선제 제외("돼지고기 빼고")
        recipes = ctx.recipes
        disliked = set(question.disliked_item_ids)
        if disliked:
            recipes = [r for r in recipes if not (disliked & _recipe_ings(r))]
        # 이미 보여준 레시피 제외(중복 방지·"다른 추천"). 다 제외돼 없으면 무시(재노출 허용).
        shown = set(question.exclude_recipe_ids)
        if shown:
            fresh = [r for r in recipes if _as_int(r.get("recipe_id")) not in shown]
            if fresh:
                recipes = fresh
        # 예산 필터 — 재료비(부착된 것) ≤ 예산인 레시피만. 부착 0이면 미필터(폴백).
        if question.budget_won:
            affordable = [r for r in recipes if r.get("_cost") is not None and r["_cost"] <= question.budget_won]
            if affordable:
                recipes = affordable
        if question.item_ids:
            want = set(question.item_ids)
            top = [r for r in recipes[:5] if want & _recipe_ings(r)][:3]
        else:
            words = _meaningful_words(question.raw_text)
            top = [r for r in recipes[:3] if any(w in r["name"] for w in words)]
        if not top:
            if question.budget_won:
                return GeneratedAnswer(
                    text=f"{question.budget_won:,}원 예산에 맞는 요리를 아직 못 찾았어요. 예산을 조금 늘려보실래요?")
            return GeneratedAnswer(text="모르겠어요 — 관련 레시피를 찾지 못했습니다.")
        basis = [BasisTag(type="recipe_match", detail=r["name"]) for r in top]
        if question.budget_won and any(r.get("_cost") is not None for r in top):
            parts = [f"'{r['name']}'(약 {r['_cost']:,}원)" if r.get("_cost") is not None else f"'{r['name']}'" for r in top]
            text = f"{question.budget_won:,}원으로 만들 수 있는 요리예요! " + ", ".join(parts) + " 어때요?"
        else:
            text = ", ".join(f"'{r['name']}'" for r in top) + " 같은 요리는 어때요?"
        return GeneratedAnswer(text=text, basis=basis)
