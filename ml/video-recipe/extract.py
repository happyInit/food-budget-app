"""영상→레시피 추출 백엔드 — Gemini(유료, 팀 승인) / mock(키 없이 테스트·개발).

비용 원칙(video-recipe-ai.md §3): **영상 토큰이 비용의 90%+** → 1차 추출은 가장 싼 모델.
  · 추출  VIDEO_EXTRACT_MODEL (기본 gemini-flash-lite-latest) — 최저가, 영상 1회 통과
  · 재분석 VIDEO_RETRY_MODEL  (기본 gemini-flash-latest)      — 하드실패 1회만 영상 재분석
  · 정제  VIDEO_REFINE_MODEL  (기본 gemini-flash-latest)      — 텍스트만·선택적(REFINE_ENABLED)
정제는 기본 OFF(비용 절감) — 1차 추출 품질이 부족할 때만 켠다. 캐시 히트면 호출 0.
키(VIDEO_GEMINI_API_KEY) 없으면 백엔드 미가용 → 파이프라인이 안내 폴백(무동작·무비용).
"""
from __future__ import annotations

import json
import os

from models import Ingredient, RecipeExtraction, Step

_SCHEMA_PROMPT = (
    "다음 유튜브 요리 영상을 보고 레시피를 JSON으로만 추출해라. 형식:\n"
    '{"title":str|null,"is_recipe":bool,"servings":str|null,'
    '"ingredients":[{"name":str,"quantity":str|null}],'
    '"steps":[{"order":int,"text":str,"timestamp_sec":int}],"video_seconds":int}\n'
    "규칙: 재료명은 원문 그대로. steps.order는 1부터 단조증가, timestamp_sec는 실제 영상 시각(초)로 "
    "단조증가. 요리 영상이 아니면 is_recipe=false, title=null. JSON 외 텍스트 금지."
)


def _model(env: str, default: str) -> str:
    return os.environ.get(env, default)


def available() -> bool:
    """Gemini 추출 가용 여부 — 키 있어야 함."""
    return bool(os.environ.get("VIDEO_GEMINI_API_KEY"))


def _parse(text: str, url: str) -> RecipeExtraction:
    """모델 텍스트 → RecipeExtraction. 파싱/스키마 실패는 호출측이 H1로 처리."""
    s = text.strip()
    if s.startswith("```"):                       # ```json ... ``` 펜스 제거
        s = s.split("```", 2)[1].lstrip("json").strip() if "```" in s[3:] else s.strip("`")
    d = json.loads(s)
    return RecipeExtraction(
        title=d.get("title"), is_recipe=bool(d.get("is_recipe", True)), servings=d.get("servings"),
        ingredients=[Ingredient(name=i["name"], quantity=i.get("quantity")) for i in d.get("ingredients", [])],
        steps=[Step(order=st["order"], text=st["text"], timestamp_sec=st.get("timestamp_sec")) for st in d.get("steps", [])],
        source_url=url, video_seconds=d.get("video_seconds"),
    )


def gemini_extract(url: str, model_env: str = "VIDEO_EXTRACT_MODEL",
                   default_model: str = "gemini-flash-lite-latest") -> RecipeExtraction:
    """Gemini로 유튜브 URL 직접 분석 → RecipeExtraction. 예외는 호출측(파이프라인)이 하드실패 처리."""
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["VIDEO_GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model=_model(model_env, default_model),
        contents=types.Content(parts=[
            types.Part(file_data=types.FileData(file_uri=url)),
            types.Part(text=_SCHEMA_PROMPT),
        ]),
    )
    return _parse(resp.text or "", url)


def refine_enabled() -> bool:
    return os.environ.get("VIDEO_REFINE_ENABLED", "false").lower() == "true"
