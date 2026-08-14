"""Bedrock RCA prompt and tool-call schema design.

This module has no AWS SDK dependency (same boundary rule as app.rca_contract).
It only defines *what* to send to a Bedrock model and *what shape* the answer
must come back in. The actual bedrock-runtime call belongs in app.rca_contract
(build_bedrock_rca), which will import from here.

Design choices, and why:
- Tool use (function calling), not "please reply with JSON" prose instructions.
  Free-text JSON coaxing is unreliable; Bedrock's Converse API tool_choice
  forces the model to answer through a schema, which Pydantic can then
  validate directly against app.rca_contract.RcaAnalysisResponse.
- Every RcaEvidenceReference.reference_id must be an ID that already exists
  in the EvidencePackage that was sent. The system prompt states this as a
  hard rule and the per-source ID mapping below documents which field to
  use for each source (some evidence types have no natural ID field, so a
  composite key is defined instead).
- The model never invents anomaly scores, merges alerts, or issues a final
  verdict. This mirrors docs/operations-ai-roadmap.md §8 운영 원칙: Bedrock
  only interprets Evidence that a deterministic pipeline already assembled.
"""

from __future__ import annotations

import json
from typing import Any

from app.models import EvidencePackage

# --- Per-source reference_id mapping -----------------------------------
# EvidencePackage 필드마다 "고유 ID로 쓸 필드"가 다르다. log·deployment는
# 별도 ID 필드가 없어서 조합 키를 만든다. 이 매핑은 시스템 프롬프트에도
# 그대로 명시해서, 모델이 존재하지 않는 ID를 지어내지 않게 한다.
#
#   alert            -> NormalizedAlert.alert_id
#   anomaly          -> EvidenceAnomaly.metric_id
#   log              -> f"{namespace}/{container}:{pattern[:40]}"  (LogPatternEvidence는 ID 필드 없음)
#   trace            -> TraceEvidence.trace_id
#   kubernetes_event -> KubernetesEventEvidence.event_id
#   deployment       -> f"{namespace}/{deployment}"                (DeploymentEvidence는 ID 필드 없음)

SYSTEM_PROMPT = """\
당신은 Kubernetes 기반 마이크로서비스 운영 환경의 원인분석(RCA) 보조자입니다.
당신에게는 이미 결정론적 파이프라인이 수집·선별한 Evidence(사실 데이터)가 JSON으로
주어집니다. 이 Evidence 밖의 사실을 추측하거나 지어내지 마세요.

절대 규칙:
1. 최종 판정이 아니라 "조사 초안(draft)"을 작성하세요. 엔지니어가 최종 원인과 조치를
   직접 확인합니다. 확신에 찬 단정적 표현(반드시, 확실히 등)을 쓰지 마세요.
2. anomaly 점수나 alert 병합 여부를 새로 판단하지 마세요 — 이미 파이프라인이
   결정했습니다. 당신의 역할은 "왜 이런 패턴이 함께 나타났는지" 해석하는 것입니다.
3. causes[].evidence[]의 reference_id는 반드시 입력 Evidence에 실제로 존재하는
   ID만 사용하세요. 존재하지 않는 ID를 만들어내면 안 됩니다. 항목별 ID는 이렇습니다:
   - alert → alert_id 값 그대로
   - anomaly → metric_id 값 그대로
   - log → "{namespace}/{container}:{pattern 앞 40자}" 형태로 직접 조합
   - trace → trace_id 값 그대로
   - kubernetes_event → event_id 값 그대로
   - deployment → "{namespace}/{deployment}" 형태로 직접 조합
4. Evidence 중 비어 있거나 unavailable_sources에 포함된 항목은 "그 종류의 근거는
   확인하지 못했다"고 limitations에 명시하세요. 없는 데이터를 있는 것처럼 다루지
   마세요.
5. causes는 가능성이 높은 순서로 rank를 매기세요(1이 가장 유력). 각 cause는 최소
   1개 이상의 evidence 참조가 있어야 합니다.
   각 cause의 analysis에는 "관측값 → 이 가설을 세운 이유 → 아직 확정할 수 없는 이유"를
   2~4문장으로 구체적으로 작성하세요.
   Evidence가 Alert 하나뿐이어도 causes/checks/recommendations를 빈 배열로 두지 마세요.
   그 Alert를 인용해 "근거 부족으로 원인 미확정"인 low confidence 후보와, 다음 확인
   행동 및 자동 실행하지 않는 권고를 각각 최소 1개 작성하세요.
6. propagation_path는 incident의 suspected_origin_service에서 시작해 실제 Evidence로
   뒷받침되는 서비스 전파 경로만 적으세요. 근거 없는 서비스를 경로에 넣지 마세요.
7. checks는 엔지니어가 다음에 무엇을 확인해야 하는지 구체적 행동으로, recommendations는
   즉시 실행하지 말고 검토 후 적용할 조치로 작성하세요. recommendations를 자동 실행
   지시처럼 쓰지 마세요.
8. 반드시 제공된 도구(submit_rca_draft)를 호출해서 답하세요. 도구 호출 없이 텍스트로만
   답하지 마세요.
9. summary, analysis, action, expected_signal, rationale, limitations의 자연어 값은 한국어로 작성하세요.
10. checks마다 실제 Evidence의 namespace/pod/service를 사용해 실행 가능한 읽기 전용
    확인 명령을 read_only_commands에 1~3개 반드시 제시하세요. anomaly labels에 pod와
    namespace가 있으면 kubectl describe pod, kubectl get pod, kubectl logs 중 적절한 명령을
    사용하세요. 삭제·재시작·scale·patch 같은 변경 명령은 넣지 마세요.
11. recommendations에는 변경·완화 조치가 필요할 때만 precondition에 "언제 실행할지"를
    명시하세요. 근거가 부족하면 원인 미확정과 추가 수집을 권고하세요.
12. 운영자 리포트 형식을 따르세요. cause.summary는 한 줄 결론, cause.analysis는
    "관측 근거 → 원인 가설 → 확정 불가 사유" 순서로 작성하세요. checks는 즉시 조치와
    확인 명령, recommendations는 미조치 시 영향과 조건부 수정·완화 조치를 작성하세요.
"""


def format_evidence_for_prompt(evidence: EvidencePackage) -> str:
    """Serialize EvidencePackage into the user-turn content sent to the model.

    Compact JSON, not a natural-language paraphrase — paraphrasing before the
    model sees it risks losing exact IDs the model must cite back.
    """
    payload: dict[str, Any] = evidence.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


# --- Bedrock Converse API tool schema -----------------------------------
# RcaAnalysisResponse 중 우리 코드가 채우는 필드(contract_version·provider·status·
# incident_id·generated_at)는 도구 입력에서 제외한다 — 모델이 그 값을 짓지 않게
# 원천 차단하고, 호출부(app.rca_contract.build_bedrock_rca)가 응답을 조립할 때
# 그 필드들을 직접 채운다.

RCA_TOOL_NAME = "submit_rca_draft"

RCA_TOOL_SCHEMA: dict[str, Any] = {
    "toolSpec": {
        "name": RCA_TOOL_NAME,
        "description": (
            "Submit the RCA investigation draft. Must be called exactly once, "
            "using only IDs that exist in the Evidence you were given."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "additionalProperties": False,
                "required": ["causes", "propagation_path", "checks", "recommendations", "limitations"],
                "properties": {
                    "causes": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["rank", "summary", "confidence", "analysis", "evidence"],
                            "properties": {
                                "rank": {"type": "integer", "minimum": 1},
                                "summary": {"type": "string", "minLength": 1},
                                "confidence": {"enum": ["low", "medium", "high"]},
                                "analysis": {"type": "string", "minLength": 1},
                                "evidence": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["source", "reference_id", "summary"],
                                        "properties": {
                                            "source": {
                                                "enum": [
                                                    "alert",
                                                    "anomaly",
                                                    "log",
                                                    "trace",
                                                    "kubernetes_event",
                                                    "deployment",
                                                ]
                                            },
                                            "reference_id": {"type": "string", "minLength": 1},
                                            "summary": {"type": "string", "minLength": 1},
                                        },
                                    },
                                },
                            },
                        },
                    },
                    "propagation_path": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["service", "observation"],
                            "properties": {
                                "service": {"type": "string", "minLength": 1},
                                "observation": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                    "checks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["rank", "action", "expected_signal", "read_only_commands"],
                            "properties": {
                                "rank": {"type": "integer", "minimum": 1},
                                "action": {"type": "string", "minLength": 1},
                                "expected_signal": {"type": "string", "minLength": 1},
                                "read_only_commands": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "string", "minLength": 1}},
                            },
                        },
                    },
                    "recommendations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["priority", "action", "rationale"],
                            "properties": {
                                "priority": {"enum": ["p0", "p1", "p2", "p3"]},
                                "action": {"type": "string", "minLength": 1},
                                "rationale": {"type": "string", "minLength": 1},
                                "precondition": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                    "limitations": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                },
            }
        },
    }
}
