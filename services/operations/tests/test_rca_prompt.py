from __future__ import annotations

import json
from datetime import datetime, timezone

from app.models import EvidenceAnomaly, EvidencePackage, IncidentCandidate, NormalizedAlert
from app.rca_contract import RcaCause, RcaCheck, RcaPropagationHop, RcaRecommendation
from app.rca_prompt import (
    RCA_TOOL_NAME,
    RCA_TOOL_SCHEMA,
    SYSTEM_PROMPT,
    format_evidence_for_prompt,
)


def _evidence() -> EvidencePackage:
    captured_at = datetime(2026, 8, 1, 3, 0, tzinfo=timezone.utc)
    alert = NormalizedAlert(
        alert_id="recipe-latency",
        status="firing",
        alert_name="AppHighP95Latency",
        service="recipe",
        severity="warning",
        starts_at=captured_at,
        received_at=captured_at,
        labels={"service": "recipe"},
        annotations={},
    )
    incident = IncidentCandidate(
        incident_id="incident-recipe-latency",
        title="recipe incident candidate",
        first_seen_at=captured_at,
        last_seen_at=captured_at,
        earliest_alert_id=alert.alert_id,
        earliest_alert_name=alert.alert_name,
        suspected_origin_service="recipe",
        affected_services=["recipe"],
        alert_count=1,
        grouping_reasons=["same_service"],
        alerts=[alert],
    )
    anomaly = EvidenceAnomaly(
        metric_id="service_p95_latency",
        subject_type="service",
        subject_key="recipe",
        labels={"service": "recipe"},
        evaluated_at=captured_at,
        status="anomaly",
        current_value=842.0,
        breached_checks=["z_score"],
        consecutive_breaches=3,
        required_consecutive_windows=3,
        selection_reasons=["same_service"],
    )
    return EvidencePackage(
        incident=incident,
        generated_at=captured_at,
        selection_window_start=captured_at,
        selection_window_end=captured_at,
        anomalies=[anomaly],
        alerts=[alert],
    )


def test_format_evidence_for_prompt_is_valid_json_with_real_ids():
    rendered = format_evidence_for_prompt(_evidence())

    parsed = json.loads(rendered)
    assert parsed["incident"]["incident_id"] == "incident-recipe-latency"
    assert parsed["alerts"][0]["alert_id"] == "recipe-latency"
    assert parsed["anomalies"][0]["metric_id"] == "service_p95_latency"


def test_system_prompt_documents_the_id_rule_and_forces_tool_use():
    assert "reference_id" in SYSTEM_PROMPT
    assert RCA_TOOL_NAME in SYSTEM_PROMPT


def test_tool_schema_field_names_match_the_rca_contract_models():
    props = RCA_TOOL_SCHEMA["toolSpec"]["inputSchema"]["json"]["properties"]

    cause_props = set(props["causes"]["items"]["properties"])
    assert cause_props == set(RcaCause.model_fields)

    hop_props = set(props["propagation_path"]["items"]["properties"])
    assert hop_props == set(RcaPropagationHop.model_fields)

    check_props = set(props["checks"]["items"]["properties"])
    assert check_props == set(RcaCheck.model_fields)

    recommendation_props = set(props["recommendations"]["items"]["properties"])
    assert recommendation_props == set(RcaRecommendation.model_fields)


def test_tool_schema_name_is_unique_and_present():
    assert RCA_TOOL_SCHEMA["toolSpec"]["name"] == RCA_TOOL_NAME
