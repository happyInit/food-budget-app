from __future__ import annotations

from app.chat_prompt import SYSTEM_PROMPT, format_chat_context_for_prompt


def test_system_prompt_tells_the_model_not_to_guess_missing_data():
    assert "수집되지" in SYSTEM_PROMPT


def test_system_prompt_defers_root_cause_analysis_to_the_rca_flow():
    assert "RCA" in SYSTEM_PROMPT


def test_format_chat_context_serializes_snapshot_as_json():
    snapshot = {"active_anomaly_count": 2, "metrics": {"available": True, "cpu_cores_used": 1.5}}
    rendered = format_chat_context_for_prompt(snapshot)
    assert '"active_anomaly_count": 2' in rendered
    assert '"cpu_cores_used": 1.5' in rendered
