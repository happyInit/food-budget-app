"""GeminiGenerator — ④ 생성 층의 LLM 다듬기 구현 (opt-in, GENERATOR_BACKEND=gemini).

설계(docs/chat-assistant-ai.md §2·§3)의 "DB 병렬조회 → 컨텍스트 조립 → LLM이 응답을
다듬는다"를 그대로 구현. 핵심 원칙:

  1. TemplateGenerator를 근거 바닥(floor)으로 품는다. template이 거절("모르겠어요")하면
     Gemini를 호출하지 않는다 → 오프토픽/무근거 질문은 비용 0 + 거절 게이트·95% 정답률 유지.
  2. 응답이 있을 때만 template의 근거 사실을 Gemini에 넘겨 자연스러운 문장으로 재작성.
     basis(근거 태그)는 template 것을 그대로 유지 — 근거는 검색결과에서만 나온다.
  3. 근거대조(check_output_grounded): 근거 밖 숫자를 지어내면 template 출력으로 fallback.
     타임아웃·API오류도 전부 template fallback → 요청 실패 없음.

비용 최소화 레버:
  - 거절 건 skip(호출 0)  · Flash-Lite · max_output_tokens 작게 · temperature 낮게
  - 선택적 다듬기: 가격·영양 응답은 이미 깔끔한 구조화 사실이라 Gemini skip, 레시피 추천만 다듬음
  - Redis 캐시: 동일 근거(grounded_text)면 재호출 없이 캐시된 다듬기 결과 반환(0원)
"""
from __future__ import annotations

import asyncio
import hashlib

from app.config import settings
from app.models import ExtractedQuery
from app.pipeline.context import AssembledContext
from app.pipeline.generator.base import GeneratedAnswer, Generator
from app.pipeline.generator.template import TemplateGenerator
from app.pipeline.guardrails import check_output_grounded, expand_korean_amounts, incr_monthly_calls

# 아래 규칙은 전부 **실측으로 도출**됐다 — 각 블록은 계측에서 실제로 관측된 실패를 직격한다.
#   근거: docs/ai-chat-mass-measurement.md (1,138건 × 4라운드) · docs/ai-model-quality-uplift.md (실험 A~H)
#   Gemini·Nova 양쪽에서 개선 또는 무해임을 확인하고 공유 프롬프트로 둔다(회귀 검증 §6).
_SYSTEM = (
    "너는 '월 식비 예산 밀플래닝' 앱의 어시스턴트야. "
    "아래 [근거]는 앱 DB에서 검색된 확정 사실이다. "
    "이 근거에 있는 내용만 사용해 사용자 [질문]에 친근하고 자연스러운 한국어로 답하라. "
    "근거에 없는 레시피·가격·숫자·재료를 절대 추가하거나 지어내지 마라. "
    "2~4문장으로 간결하게. 레시피 이름은 근거에 적힌 그대로 사용하라.\n"

    # ① 지식경계 창작 — 근거에 조리법이 없는데 지어내던 실패(실험 B: 전 모델 0/3 → 3/3)
    "\n[중요] 근거에 조리법·재료가 없으면 **절대 지어내지 마라**. "
    "그럴 때는 근거에 있는 요리 이름만 언급하고, 상세 레시피는 앱에서 확인하도록 안내하라.\n"
    "좋은 예)\n"
    "  [근거] '김치찌개' 같은 요리는 어때요?\n"
    "  [답변] '김치찌개' 같은 요리는 어때요? 자세한 재료와 조리법은 앱에서 확인해 보세요!\n"
    "나쁜 예) '김치찌개는 김치와 돼지고기, 두부를 넣고 끓입니다' "
    "← 근거에 없는 재료·조리법을 지어냄. 절대 금지.\n"

    # ② 금액 누락 — 요약하며 가격을 흘리던 실패(실험 G: HARD-25 12/25 → 23/25)
    "\n[숫자 보존 — 매우 중요] 근거에 적힌 **모든 숫자(금액·kcal·g·mg·인분)를 하나도 빠짐없이** "
    "답변에 그대로 포함하라. 요약하거나 생략하지 마라. 금액은 근거에 적힌 형식 그대로 쓴다.\n"
    "좋은 예)\n"
    "  [근거] 10000원으로 만들 수 있는 요리예요! '김치찌개'(약 5,200원), '순두부찌개'(약 4,800원) 어때요?\n"
    "  [답변] 10,000원으로 '김치찌개'(약 5,200원), '순두부찌개'(약 4,800원) 만들 수 있어요!\n"
    "나쁜 예) '김치찌개', '순두부찌개' 어때요? ← **가격을 빠뜨림. 절대 금지.**\n"

    # ③ 이름 누락 — 다품목에서 1개만 남기던 최대 결함(대규모 계측: 87건 → 21건)
    "\n[요리 이름 전량 나열 — 가장 흔한 실수] 근거에 작은따옴표(')로 묶인 요리 이름이 N개면 "
    "**답변에도 반드시 N개가 모두** 나와야 한다. 개수를 줄이거나 대표 하나만 고르지 마라.\n"
    "좋은 예)\n"
    "  [근거] '탕수육', '애호박전', '무생채', '알탕', '카레', '삼계탕' 같은 요리는 어때요?\n"
    "  [답변] '탕수육', '애호박전', '무생채', '알탕', '카레', '삼계탕' 어때요? "
    "자세한 재료는 앱에서 확인해 보세요!\n"
    "나쁜 예) '알탕' 같은 요리는 어때요? ← **6개 중 1개만 언급. 절대 금지.**\n"

    # ④ 질문 에코 — 질문 텍스트를 요리명처럼 인용하던 버그성 동작(계측 11건)
    "\n[작은따옴표는 요리 이름 전용] 질문에 나온 재료명·문장을 작은따옴표로 인용하지 마라. "
    "작은따옴표는 **근거에 적힌 요리 이름에만** 쓴다.\n"
    "나쁜 예) 질문 \"연근이랑 계란으로 뭐 해먹지\" → 답변 \"'연근랑계란' 같은 요리는 어때요?\" "
    "← **질문을 요리 이름처럼 인용. 절대 금지.**\n"

    # ⑤ 항목 접기 — 여러 줄 근거를 "앱에서 확인"으로 뭉개던 실패(Gemini 금액손실 5건 → 0건)
    "\n[여러 줄 근거는 항목을 접지 마라] 근거가 `· 재료 금액` 형태로 여러 줄이면 "
    "**모든 줄의 재료와 금액을 답변에 포함**하라. "
    "\"자세한 내용은 앱에서 확인하세요\"로 대체하고 항목을 생략하면 안 된다."
)


class GeminiGenerator(Generator):
    def __init__(self, redis_client=None, ingredient_index: dict[str, int] | None = None) -> None:
        from google import genai  # 지연 import — 백엔드 미사용 시 의존성 불필요

        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY 없음 — .env 확인 (GENERATOR_BACKEND=gemini 사용 시 필수)")
        self._template = TemplateGenerator()
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._types = __import__("google.genai.types", fromlist=["types"])
        self._redis = redis_client
        self._ingredient_index = ingredient_index   # 근거대조 재료 어휘(표면형→item_id). None이면 숫자만 대조

    async def generate(self, question: ExtractedQuery, ctx: AssembledContext) -> GeneratedAnswer:
        base = await self._template.generate(question, ctx)
        if not base.basis:
            return base  # 거절 케이스 — Gemini 호출 안 함(비용 0, 게이트 보존)
        if settings.gemini_refine_recommend_only and not any(b.type == "recipe_match" for b in base.basis):
            return base  # 가격·영양 = 이미 깔끔한 구조화 사실 → 다듬기 skip

        cached = await self._cache_get(base.text)
        if cached is not None:
            return GeneratedAnswer(text=cached, basis=base.basis)

        try:
            polished = await asyncio.wait_for(
                self._refine(question.raw_text, base.text), timeout=settings.gemini_timeout_s
            )
        except Exception:  # noqa: BLE001 — 타임아웃·API오류 무엇이든 template로 안전 fallback
            return base
        # 실제 유료 호출 1건 발생(캐시히트·거절·recommend-only skip은 여기 못 옴) → 월 비용 계상.
        if settings.monthly_cap_enabled:
            await incr_monthly_calls(self._redis)
        # 근거 = template 출력 + 유저 질문 + 질문의 금액 표기 확장("8천원"→8000).
        # 유저가 말한 재료·예산을 되풀이하는 것은 환각이 아니므로 오탐을 막는다(guardrails 독스트링 참조).
        q = question.raw_text
        grounding_ref = f"{base.text}\n{q}\n{expand_korean_amounts(q)}"
        if not polished or not check_output_grounded(polished, grounding_ref, self._ingredient_index):
            return base  # 무근거 숫자·재료 환각 → template 출력 유지
        await self._cache_set(base.text, polished)
        return GeneratedAnswer(text=polished, basis=base.basis)

    async def _refine(self, question: str, grounded_text: str) -> str:
        resp = await self._client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=f"[질문]\n{question}\n\n[근거]\n{grounded_text}",
            config=self._types.GenerateContentConfig(
                system_instruction=_SYSTEM,
                max_output_tokens=settings.gemini_max_output_tokens,
                temperature=settings.gemini_temperature,
            ),
        )
        return (resp.text or "").strip()

    def _cache_key(self, grounded_text: str) -> str:
        h = hashlib.sha1(f"{settings.gemini_model}\n{grounded_text}".encode()).hexdigest()
        return f"chatgen:refine:{h}"

    async def _cache_get(self, grounded_text: str) -> str | None:
        if self._redis is None:
            return None
        try:
            return await self._redis.get(self._cache_key(grounded_text))
        except Exception:  # noqa: BLE001 — 캐시는 best-effort, 장애 시 그냥 재생성
            return None

    async def _cache_set(self, grounded_text: str, polished: str) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(self._cache_key(grounded_text), polished, ex=settings.gemini_cache_ttl_s)
        except Exception:  # noqa: BLE001
            pass
