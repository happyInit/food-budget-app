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
      0. `GCP_SA_KEY_JSON` = 서비스 계정 JSON **원문**                ← K8s 권장(아래)
      1. `GOOGLE_APPLICATION_CREDENTIALS` = 서비스 계정 JSON 경로  ← 로컬/CI
      2. `gcloud auth application-default login` 이 만든 로컬 ADC   ← 개발자 PC
      3. GCE/GKE 메타데이터 서버                                    ← 클라우드 내부
    ADC 가 없으면 `DefaultCredentialsError` 가 나며, 그 메시지는 키 오류와 달라 진단이 쉽다.

📦 **0번(JSON 원문)을 K8s 기본으로 둔 이유** — 우리 클러스터 제약에 파일 경로가 안 맞는다:
  · `app` 네임스페이스는 PodSecurity **enforce=restricted**, 컨테이너는 `readOnlyRootFilesystem`
    에 비루트(uid 10001)다. 키를 파일로 주려면 볼륨·`defaultMode`·마운트 경로까지 **Deployment
    매니페스트를 고쳐야** 하는데, 그 매니페스트는 별도 GitOps 저장소(`mealplanning-config`)에 있다.
  · 반면 `envFrom: secretRef: mp-ocr-secrets` 는 **이미 걸려 있다.** 키를 env 로 받으면
    ExternalSecret 에 항목 한 줄만 늘리면 되고 **Deployment 는 손대지 않는다.**
    배선 diff 가 작을수록 운영에서 깨질 자리가 적다.
  · 파일 경로 방식(1번)도 **그대로 살아 있다** — 로컬·CI 는 지금처럼 쓰면 된다.

⚠️ **Vertex 호환성은 PoC 로 확인해야 한다**(계획서 §3.2) — 특히 `thinking_config`.
   별칭 드리프트로 이 인자가 거부돼 OCR 이 전량 실패한 사고 이력이 있다(PR #272).
   호출측(`vision.py`)에 이미 "거부되면 thinking 빼고 재시도" 폴백이 있어 서비스는 유지된다.
"""
from __future__ import annotations


class GenaiConfigError(RuntimeError):
    """클라이언트 생성에 필요한 설정이 없다 — 키 부재·프로젝트 미지정 등."""


def _credentials_from_json(raw: str):
    """서비스 계정 JSON **원문** → `google.oauth2` 자격증명.

    🔴 이 함수는 예외 메시지에 `raw` 를 절대 넣지 않는다 — 키가 로그로 새는 가장 흔한 경로다.
    """
    import json  # noqa: PLC0415

    from google.oauth2 import service_account  # noqa: PLC0415

    try:
        info = json.loads(raw)
    except ValueError as exc:
        raise GenaiConfigError(
            "GCP_SA_KEY_JSON 파싱 실패 — 서비스 계정 키 **JSON 원문**이어야 한다"
            "(파일 경로·base64 가 아니다). 값은 로그에 남기지 않는다.") from exc
    try:
        # cloud-platform 스코프를 명시한다 — 서비스 계정 자격증명은 스코프가 비면
        # Vertex 호출이 403 으로 떨어진다(키는 맞는데 권한이 없다는 혼란스러운 실패).
        return service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    except Exception as exc:
        raise GenaiConfigError(
            f"GCP_SA_KEY_JSON 이 서비스 계정 키 형식이 아니다({type(exc).__name__}) — "
            "`type: service_account`·`private_key`·`client_email` 필드를 확인할 것") from exc


def make_client(backend: str, *, api_key: str = "", project: str = "", location: str = "",
                sa_key_json: str = ""):
    """backend('api_key'|'vertex') → `google.genai.Client`.

    지연 import — 이 백엔드를 안 쓰는 배포에서는 의존성이 필요 없다.

    `sa_key_json` 이 비어 있으면 **기존 ADC 경로 그대로**다(하위호환) — 로컬·CI 는 영향 없다.
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
        # JSON 원문이 있으면 그것으로, 없으면 종전대로 ADC 자동탐색에 맡긴다.
        creds = _credentials_from_json(sa_key_json) if sa_key_json else None
        return genai.Client(vertexai=True, project=project, location=location,
                            credentials=creds)

    if backend == "api_key":
        if not api_key:
            raise GenaiConfigError("GEMINI_API_KEY 없음 — .env 확인 (api_key 백엔드 필수)")
        return genai.Client(api_key=api_key)

    raise GenaiConfigError(f"알 수 없는 backend={backend!r} (api_key|vertex)")
