"""영상→레시피 추출 백엔드 — Gemini(유료, 팀 승인) / mock(키 없이 테스트·개발).

비용 원칙(video-recipe-ai.md §3): **영상 토큰이 비용의 90%+** → 1차 추출은 가장 싼 모델.
  · 추출  VIDEO_EXTRACT_MODEL (기본 gemini-3.5-flash-lite) — 최저가, 영상 1회 통과
  · 재분석 VIDEO_RETRY_MODEL  (기본 gemini-3.5-flash)      — 하드실패 1회만 영상 재분석
  · 정제  VIDEO_REFINE_MODEL  (기본 gemini-3.5-flash)      — 텍스트만·선택적(REFINE_ENABLED)
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
    "단조증가. 요리 영상이 아니면 is_recipe=false, title=null. JSON 외 텍스트 금지.\n"

    # ── 스텝 서술 규칙 ────────────────────────────────────────────────────
    # 유저는 이 텍스트만 보고 요리한다 — 영상을 다시 돌려보지 않아도 되게 써야 한다.
    "\n[조리 순서 작성 규칙]\n"
    "- 각 스텝은 **한두 문장**으로 쓴다. 한 문장이면 짧고, 필요할 때만 두 번째 문장으로 보충한다.\n"
    "- **동작 하나에 스텝 하나**. 여러 동작을 한 스텝에 몰아넣지 말고, 반대로 한 동작을 쪼개지도 마라.\n"
    "- **수치를 반드시 포함**한다 — 분량(3컵·1큰술)·시간(10분)·불세기(중불)·상태(끓어오르면). "
    "영상에서 말한 값을 그대로 쓰고, 없는 값을 지어내지 마라.\n"
    "- 앞뒤 스텝이 **자연스럽게 이어지게** 쓴다. 이전 스텝의 결과를 받아 다음 동작을 지시하라"
    "(예: \"육수가 끓어오르면 …\"). 문맥 없이 뚝 끊긴 명령문만 나열하지 마라.\n"
    "- 재료 손질처럼 **대기 중에 하는 작업**도 순서에 포함한다(끓이는 동안 채소 썰기 등).\n"
    "- 영상 속 **유용한 팁**(대체 재료·주의점)은 해당 스텝의 두 번째 문장이나 괄호로 덧붙인다.\n"
    "- 인사말·구독 요청·잡담은 제외한다. 조리와 무관한 내용은 스텝이 아니다.\n"
    "- 최소 3스텝 이상으로 조리 과정을 빠짐없이 담는다(준비 → 조리 → 마무리).\n"

    # 실측(2026-07-29): 1차 모델이 3회 중 1회 타임스탬프를 역순으로 냈다([191,444,393,…]).
    # 재분석이 잡아주지만 그만큼 비용·지연이 든다 → 규칙을 명시해 1차 성공률을 올린다.
    "- **timestamp_sec는 반드시 오름차순**이어야 한다. 스텝을 다 쓴 뒤 시각이 앞 스텝보다 "
    "작아지는 곳이 없는지 검토하고, 영상 길이(video_seconds)를 넘는 값도 없어야 한다.\n"

    # 실측(2026-07-29): servings가 3회 중 1회만 채워졌다. 재료비를 1인분으로 환산하려면 필요하다.
    # 단 **없는 값을 지어내면 안 된다** — 잘못된 인분은 재료비를 그만큼 틀리게 만든다.
    "\n[인분(servings)]\n"
    "- 진행자가 말하거나 화면에 표시된 인분을 그대로 쓴다(\"2인분\", \"2~3인분\").\n"
    "- 명시가 없으면 **재료 분량으로 추정하지 말고 null**로 둔다. 틀린 인분은 재료비 계산을 "
    "그대로 왜곡하므로, 모르면 비워 두는 편이 낫다."
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
                   default_model: str = "gemini-3.5-flash-lite") -> RecipeExtraction:
    """Gemini로 유튜브 URL 직접 분석 → RecipeExtraction. 예외는 호출측(파이프라인)이 하드실패 처리."""
    from google import genai
    from google.genai import types

    # ── 백엔드 토글 (docs/gcp-migration-plan.md §3.1) ────────────────────────
    # api_key(기본) = 개인 키 · vertex = 팀 GCP Vertex AI(ADC 인증).
    # ✅ 계획서 §4.2 PoC 완료(2026-07-29) — Vertex 도 YouTube URL 입력을 지원하나
    #    **요청 형태가 더 엄격**하다. 실측한 두 가지 필수 조건은 아래 contents 참조.
    backend = os.environ.get("VIDEO_GENAI_BACKEND", "api_key")
    if backend == "vertex":
        project = os.environ.get("GCP_PROJECT_ID", "")
        location = os.environ.get("GCP_LOCATION", "")
        if not project or not location:
            raise RuntimeError(
                "VIDEO_GENAI_BACKEND=vertex 인데 GCP_PROJECT_ID/GCP_LOCATION 이 없다. "
                "리전은 기본값을 두지 않는다 — 데이터 레지던시를 결정하기 때문(계획서 §7-1).")
        client = genai.Client(vertexai=True, project=project, location=location)
    else:
        client = genai.Client(api_key=os.environ["VIDEO_GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model=_model(model_env, default_model),
        # role·mime_type 은 **Vertex 필수**다(api_key 는 생략해도 동작). 실측 오류:
        #   role 없음      → 400 "Please use a valid role: user, model."
        #   mime_type 없음 → 400 "empty mimeType parameter in fileData"
        # 두 백엔드가 같은 형태를 받으므로 분기 없이 공통으로 둔다(api_key 회귀 없음 확인).
        contents=types.Content(role="user", parts=[
            types.Part(file_data=types.FileData(file_uri=url, mime_type="video/*")),
            types.Part(text=_SCHEMA_PROMPT),
        ]),
    )
    return _parse(resp.text or "", url)


def refine_enabled() -> bool:
    return os.environ.get("VIDEO_REFINE_ENABLED", "false").lower() == "true"
