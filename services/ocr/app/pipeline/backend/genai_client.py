"""Gemini 클라이언트 팩토리 — Google AI API(개인 키) / Vertex AI(팀 GCP) 토글.

`google-genai` 는 **통합 SDK** 라 두 백엔드를 같은 인터페이스로 쓴다. 전환은 클라이언트 생성
한 줄이고 `generate_content` · `types.Part` · `FileData` · 프롬프트는 **전부 그대로**다
(`docs/gcp-migration-plan.md` §3).

    api_key 모드 : genai.Client(api_key=...)                        ← 현행(기본)
    vertex 모드  : genai.Client(vertexai=True, project=..., location=...)

**현행 경로를 지우지 않는다.** `OCR_BACKEND`·`GENERATOR_BACKEND` 와 같은 env 토글 패턴이라
Vertex 에서 문제가 나면 env 하나로 즉시 되돌아온다 — 되돌아올 수 없는 마이그레이션을 만들지
않는 것이 이 설계의 핵심이다(계획서 §3.1).

⚠️ **인증 방식이 다르다.**
  · api_key — 환경변수 하나. 개인 키.
  · vertex  — **ADC**(Application Default Credentials). 키 문자열이 아니라 다음 중 하나로 잡힌다:
      1. `GOOGLE_APPLICATION_CREDENTIALS` = 서비스 계정 JSON 경로  ← 컨테이너/CI 권장
      2. `gcloud auth application-default login` 이 만든 로컬 ADC   ← 개발자 PC
      3. GCE/GKE 메타데이터 서버                                    ← 클라우드 내부
    ADC 가 없으면 `DefaultCredentialsError` 가 나며, 그 메시지는 키 오류와 달라 진단이 쉽다.

⚠️ **Vertex 호환성은 PoC 로 확인해야 한다**(계획서 §3.2) — 특히 `thinking_config`.
   별칭 드리프트로 이 인자가 거부돼 OCR 이 전량 실패한 사고 이력이 있다(PR #272).
   호출측(`vision.py`)에 이미 "거부되면 thinking 빼고 재시도" 폴백이 있어 서비스는 유지된다.
"""
from __future__ import annotations


class GenaiConfigError(RuntimeError):
    """클라이언트 생성에 필요한 설정이 없다 — 키 부재·프로젝트 미지정 등."""


def make_client(backend: str, *, api_key: str = "", project: str = "", location: str = ""):
    """backend('api_key'|'vertex') → `google.genai.Client`.

    지연 import — 이 백엔드를 안 쓰는 배포에서는 의존성이 필요 없다.
    """
    from google import genai  # noqa: PLC0415

    if backend == "vertex":
        if not project:
            raise GenaiConfigError(
                "GCP_PROJECT_ID 없음 — Vertex 모드 필수. "
                "설정: gcloud config set project <PROJECT_ID> 후 .env 에 GCP_PROJECT_ID 기입")
        # location 은 기본값을 주지 않는다 — 리전이 데이터 레지던시를 결정하므로(계획서 §7-1)
        # 조용히 글로벌로 붙는 일이 없어야 한다.
        if not location:
            raise GenaiConfigError(
                "GCP_LOCATION 없음 — Vertex 모드 필수. 리전이 데이터 레지던시를 결정하므로 "
                "기본값을 두지 않는다(예: asia-northeast3=서울, us-central1=글로벌)")
        return genai.Client(vertexai=True, project=project, location=location)

    if backend == "api_key":
        if not api_key:
            raise GenaiConfigError("GEMINI_API_KEY 없음 — .env 확인 (api_key 백엔드 필수)")
        return genai.Client(api_key=api_key)

    raise GenaiConfigError(f"알 수 없는 backend={backend!r} (api_key|vertex)")
