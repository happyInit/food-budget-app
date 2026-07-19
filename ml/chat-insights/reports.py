"""대화 분석 리포트 — 데이터 담당 전달용(chat-conversation-data-plan §1.3·1.4).

두 종류:
  · daily     : 매일 그날 대화 집계 → 개선방향(무엇을 묻나·미응답 패턴·커버리지 갭)
  · threshold : 메시지 N건 임계 도달 시 트리거 → 품질·문제·해결안

동작: 구조화 지표(규칙, 항상)를 계산하고, REPORT_GEMINI_API_KEY가 있으면 Gemini로
**서술 분석**을 덧붙인다(#179 결정: Gemini Flash, 비용격리 전용 키). 키 없으면 지표만 —
키 주입 시 자동으로 서술이 붙는다(prep-ahead). 출력은 reports/chat/{daily,threshold}/.
"""
from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timezone

REPORTS_DIR = os.environ.get("CHAT_REPORTS_DIR", "reports/chat")


def compute_metrics(messages: list[dict]) -> dict:
    """대화 메시지 → 구조화 지표(규칙 기반, LLM 불필요)."""
    users = {m["role"] == "user" for m in messages}  # noqa: F841
    user_msgs = [m for m in messages if m.get("role") == "user"]
    n = len(user_msgs)
    intents = Counter(m.get("intent") or "unknown" for m in user_msgs)
    unanswered = [m for m in user_msgs if m.get("unanswered")]
    gap_terms = Counter()
    for m in unanswered:
        for w in (m.get("text") or "").split():
            if len(w) >= 2 and not w.isdigit():
                gap_terms[w] += 1
    item_freq = Counter()
    for m in user_msgs:
        for i in (m.get("item_ids") or []):
            item_freq[i] += 1
    return {
        "n_user_messages": n,
        "n_sessions": len({m.get("session_id") for m in user_msgs}),
        "n_users": len({m.get("user_id") for m in user_msgs if m.get("user_id") is not None}),
        "intent_distribution": dict(intents.most_common()),
        "unanswered_rate": round(len(unanswered) / n, 4) if n else 0.0,
        "coverage_gap_terms": gap_terms.most_common(10),
        "top_items": item_freq.most_common(10),
    }


def _gemini_narrative(metrics: dict, kind: str) -> str | None:
    """선택 — REPORT_GEMINI_API_KEY 있으면 서술 분석(best-effort). 없거나 실패면 None."""
    key = os.environ.get("REPORT_GEMINI_API_KEY")
    if not key:
        return None
    try:
        from google import genai  # type: ignore
        model = os.environ.get("REPORT_GEMINI_MODEL", "gemini-flash-latest")
        prompt = (f"다음은 식비 앱 챗봇의 {kind} 대화 분석 지표다. 데이터 담당자에게 줄 "
                  f"'개선방향 3가지'를 간결한 한국어 불릿으로만 써라(수치 나열 금지, 인사이트만):\n{metrics}")
        client = genai.Client(api_key=key)
        r = client.models.generate_content(model=model, contents=prompt)
        return (r.text or "").strip() or None
    except Exception:  # noqa: BLE001 — 키·SDK·네트워크 문제 → 서술 생략
        return None


def render_report(metrics: dict, kind: str, narrative: str | None) -> str:
    """지표(+서술) → 마크다운 리포트."""
    lines = [f"# 챗봇 대화 분석 리포트 ({kind})",
             f"> 생성 {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} · 유저메시지 {metrics['n_user_messages']}건 "
             f"· 세션 {metrics['n_sessions']} · 유저 {metrics['n_users']}", ""]
    lines.append("## 의도 분포")
    for k, v in metrics["intent_distribution"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", f"## 미응답률: {metrics['unanswered_rate']*100:.1f}%", "",
              "## 커버리지 갭(반복 미응답 용어)"]
    lines += [f"- {t} × {c}" for t, c in metrics["coverage_gap_terms"]] or ["- (없음)"]
    lines += ["", "## 자주 언급된 품목(item_id)"]
    lines += [f"- {i} × {c}" for i, c in metrics["top_items"]] or ["- (없음)"]
    lines += ["", "## AI 분석(개선방향)"]
    lines.append(narrative if narrative else
                 "_(REPORT_GEMINI_API_KEY 미설정 — 지표만. 키 주입 시 Gemini 서술 자동 첨부.)_")
    return "\n".join(lines) + "\n"


def write_report(text: str, kind: str, trigger: str | None = None) -> str:
    """reports/chat/{daily|threshold}/ 에 시간순 파일명으로 저장. 경로 반환."""
    now = datetime.now(timezone.utc)
    sub = "daily" if kind == "daily" else "threshold"
    if kind == "daily":
        fname = f"{now:%Y-%m-%d}.md"
    else:
        fname = f"{now:%Y-%m-%dT%H-%M}_{trigger or 'threshold'}.md"
    path = os.path.join(REPORTS_DIR, sub, fname)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return path


def generate(messages: list[dict], kind: str = "daily", trigger: str | None = None) -> tuple[str, dict]:
    """메시지 → 리포트 생성·저장. (경로, 지표) 반환."""
    metrics = compute_metrics(messages)
    narrative = _gemini_narrative(metrics, kind)
    text = render_report(metrics, kind, narrative)
    path = write_report(text, kind, trigger)
    return path, metrics
