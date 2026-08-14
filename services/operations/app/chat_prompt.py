"""Prompt construction for the dashboard chat assistant.

Kept separate from ``rca_prompt.py`` deliberately: RCA drafts an incident
investigation from a fixed Evidence Package and returns structured JSON via
forced tool use. This assistant answers ad-hoc operator questions
("서버 상태 어때?") from a lightweight current-status snapshot and returns
plain text — a different shape of problem, not a variant of RCA.
"""

from __future__ import annotations

import json

SYSTEM_PROMPT = """당신은 MealPlan Operations AI 대시보드에 내장된 운영 어시스턴트입니다.

역할:
- 아래 제공되는 "현재 상태 스냅샷"만 근거로 답한다. 스냅샷에 없는 값은 추측하지 말고
  "수집되지 않았습니다"라고 답한다.
- 질문이 특정 서비스를 가리키면 그 서비스 데이터만 본다. 전체를 묻는 질문이면 요약한다.
- 이상징후(anomaly)나 Incident에 대한 질문이면 스냅샷의 active_anomalies/open_incidents를
  근거로 답하되, 원인 분석(RCA)이 필요한 질문이면 "Incident 상세에서 RCA 조사를
  시작하세요"라고 안내한다 — 이 자리에서 원인을 추론하지 않는다.
- 간결하게 답한다. 정상이면 "정상입니다"처럼 짧게, 이상이 있으면 구체적 수치와 함께.
- 조치나 명령어를 실행하지 않는다. 텍스트로만 답한다.
"""


def format_chat_context_for_prompt(snapshot: dict) -> str:
    """Serialize the gathered status snapshot into the user turn text.

    Mirrors ``rca_prompt.format_evidence_for_prompt``'s approach: give the
    model exactly the JSON it needs to reason over, nothing implicit.
    """
    return json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)
