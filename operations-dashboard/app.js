const dashboard = window.OPERATIONS_DASHBOARD;
const $ = (selector) => document.querySelector(selector);
let activeView = "overview";
let loadError = "";
let selectedIncidentId = "";
let logSearchTerm = "";
let workloadSelection = { namespace: "all", pod: "all", container: "all" };
let expandedPanel = null;
let logSelection = { namespace: "all", pod: "all", container: "all", level: "all" };
// Logs는 기본적으로 조사 대상(ERROR/WARN)만 보여 준다. 원문 전체는 사용자가
// 명시적으로 전환했을 때만 표시해 정상 INFO 로그가 장애 조사를 덮지 않게 한다.
let logView = "issues";
let selectedLogKey = "";
let selectedTraceId = "";
let selectedTraceSummary = null;
let collapsedTraceSpanIds = new Set();
let selectedAnomalyId = "";
const operationsApiEndpoint = (path) => (new URLSearchParams(location.search).get("apiBase") || "/api") + path;

const views = {
  overview: ["OPERATIONS OVERVIEW", "서비스 운영 개요", "사용자 영향, 서비스 건강도, 활성 조사를 한 화면에서 확인합니다."],
  metrics: ["M.E.L.T · METRICS", "Metrics", "실제 Prometheus 시계열을 기준으로 서비스와 인프라 변화를 비교합니다."],
  events: ["M.E.L.T · EVENTS", "Events", "배포·이상징후·Incident의 발생 순서를 같은 시간축에서 봅니다."],
  logs: ["M.E.L.T · LOGS", "Logs", "Loki의 실제 원본 로그를 namespace·Pod·container·수준으로 탐색합니다."],
  traces: ["M.E.L.T · TRACES", "Traces", "Tempo의 느리거나 실패한 요청을 호출 경로로 조사합니다."],
  services: ["CORE SERVICES", "Services / APM", "서비스별 요청량·오류율·지연시간과 의존성을 집중 확인합니다."],
  pipeline: ["CORE SERVICES", "Data Pipeline", "가격 수집·Kafka·색인 흐름의 최신성과 지연을 확인합니다."],
  anomalies: ["INTELLIGENCE", "Anomalies · AI", "정상 기준선에서 벗어난 실제 탐지 결과를 우선순위로 확인합니다."],
  incidents: ["INTELLIGENCE", "Incidents", "관련 신호와 Evidence Snapshot을 하나의 조사 단위로 확인합니다."],
  reliability: ["RELIABILITY", "SLI / SLO", "운영 기준선이 축적된 뒤 서비스 목표와 Error Budget을 관리합니다."]
};

function text(value, fallback = "-") { return value === null || value === undefined || value === "" || Number.isNaN(value) ? fallback : String(value); }
function escapeHtml(value) { return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }
function highlightedLogMessage(value) {
  const raw = String(value || "");
  const term = logSearchTerm.trim();
  if (!term) return escapeHtml(raw);
  const literal = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return raw.split(new RegExp(`(${literal})`, "ig")).map((part) => part.toLowerCase() === term.toLowerCase()
    ? `<mark class="log-match">${escapeHtml(part)}</mark>`
    : escapeHtml(part)).join("");
}
function number(value, digits = 2) { const numeric = Number(value); return Number.isFinite(numeric) ? numeric.toLocaleString("ko-KR", { maximumFractionDigits: digits }) : "-"; }
function date(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "-";
  const hours = Number($("#periodFilter")?.value || 1);
  return hours >= 24
    ? parsed.toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })
    : parsed.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}
function hhmm(unixSeconds) { const parsed = new Date(Number(unixSeconds) * 1000); return Number.isNaN(parsed.getTime()) ? "" : parsed.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false }); }
function chartTime(unixSeconds, startSeconds, endSeconds) {
  const parsed = new Date(Number(unixSeconds) * 1000);
  if (Number.isNaN(parsed.getTime())) return "-";
  const span = Number(endSeconds) - Number(startSeconds);
  const options = span >= 86400
    ? { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }
    : { hour: "2-digit", minute: "2-digit", hour12: false };
  return new Intl.DateTimeFormat("ko-KR", options).format(parsed);
}
function fullChartTime(unixSeconds) {
  const parsed = new Date(Number(unixSeconds) * 1000);
  return Number.isNaN(parsed.getTime()) ? "-" : parsed.toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}
function tone(status) { return status === "critical" ? "critical" : status === "anomaly" || status === "warning" || status === "candidate" ? "warning" : "normal"; }
function source(name) { return dashboard.sources?.[name] || { enabled: false, label: "연결 설정 전" }; }
function sourceState(name) {
  const state = source(name);
  const label = state.enabled ? (state.label || "연결됨") : "연결 설정 전";
  return `<span class="source-state ${state.enabled ? "ready" : "waiting"}" title="${text(label)}">${state.enabled ? "LIVE" : "미연결"}</span>`;
}
function selectedService() { return (activeView === "metrics" ? $("#metricsServiceFilter")?.value : null) || $("#serviceFilter")?.value || "all"; }
function selectedNamespace() { return $("#namespaceFilter")?.value || workloadSelection.namespace; }
function selectedPod() { return $("#podFilter")?.value || workloadSelection.pod; }
function selectedContainer() { return $("#containerFilter")?.value || workloadSelection.container; }
function matchesWorkload(metric = {}, includeContainer = true) {
  return (selectedNamespace() === "all" || metric.namespace === selectedNamespace())
    && (selectedPod() === "all" || metric.pod === selectedPod())
    && (!includeContainer || selectedContainer() === "all" || metric.container === selectedContainer());
}
function filteredWorkloadSeries(series, keyFn, includeContainer = true) {
  const filtered = (series || []).filter((item) => matchesWorkload(item.metric, includeContainer));
  // 전체/namespace 수준에서는 수백 개 workload를 한 그래프에 겹치지 않고 Top 5만 본다.
  // Pod를 고르면 해당 Pod의 container들을, container를 고르면 정확히 한 series를 본다.
  const isPodScope = selectedPod() !== "all";
  const isContainerScope = includeContainer && selectedContainer() !== "all";
  return isPodScope || isContainerScope ? filtered : topSeriesByPeak(filtered, 5, keyFn);
}
function filteredWorkloadItems(items, valueFn, includeContainer = false) {
  const filtered = (items || []).filter((item) => matchesWorkload(item.metric, includeContainer));
  const isPodScope = selectedPod() !== "all";
  const isContainerScope = includeContainer && selectedContainer() !== "all";
  return isPodScope || isContainerScope ? filtered : filtered.sort((a, b) => Number(valueFn(b)) - Number(valueFn(a))).slice(0, 5);
}
function inSelectedService(service) { return selectedService() === "all" || service === selectedService(); }
function scopedAnomalies() { return (dashboard.anomalies || []).filter((item) => inSelectedService(item.service)); }
function serviceIdentity(value) { const parts = String(value || "").split("/").filter(Boolean); return parts[parts.length - 1] || "unknown"; }
const EXCLUDED_DASHBOARD_SERVICES = new Set(["account-canary", "ranking", "ranking-serving"]);
function isDashboardService(service) { return !EXCLUDED_DASHBOARD_SERVICES.has(String(service || "")); }
function selectedSeries(series) {
  const visible = (series || []).filter((item) => isDashboardService(item.metric?.service));
  if (selectedService() === "all") return visible;
  return visible.filter((item) => item.metric?.service === selectedService());
}
function topSeriesByPeak(series, count = 5, labelFor = (item) => item.metric?.service || "unknown") {
  return (series || [])
    .filter((item) => item.values?.length)
    .map((item) => ({
      ...item,
      metric: { ...item.metric, service: labelFor(item) },
      peak: Math.max(...item.values.map(([, value]) => Number(value)).filter(Number.isFinite), 0),
    }))
    .sort((a, b) => b.peak - a.peak)
    .slice(0, count);
}
function empty(title, description) { return `<section class="empty-state"><h2>${title}</h2><p>${description}</p></section>`; }
function groupedServices() { const map = new Map(); scopedAnomalies().forEach((item) => { const entry = map.get(item.service) || { service: item.service, total: 0, critical: 0, latest: item }; entry.total += 1; if (tone(item.status) === "critical") entry.critical += 1; if (new Date(item.evaluatedAt) > new Date(entry.latest.evaluatedAt)) entry.latest = item; map.set(item.service, entry); }); return [...map.values()].sort((a,b) => b.critical - a.critical || b.total - a.total); }
function anomalyBars(limit = 36) { const values = scopedAnomalies().slice(0, limit).reverse(); if (!values.length) return `<div class="no-chart">선택 기간에 실제 anomaly가 없습니다.</div>`; const max = Math.max(...values.map((item) => Math.abs(Number(item.zScore) || 1)), 1); return `<div class="anomaly-bars">${values.map((item) => `<i class="${tone(item.status)}" style="height:${Math.max(10, Math.abs(Number(item.zScore) || 1) / max * 100)}%" title="${item.metric} · ${date(item.evaluatedAt)}"></i>`).join("")}</div>`; }
function anomalyValue(value, metric) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "-";
  if (/memory|bytes|working_set/i.test(metric || "")) return `${number(numeric / 1024 / 1024, 1)} MiB`;
  // Prometheus CPU 사용량은 core 단위다. 0.01 core처럼 표시하면 9m와 11m가
  // 모두 0.01로 반올림돼 차이가 사라지므로 운영 화면에서는 mCPU로 보여 준다.
  if (/^pod_cpu_usage$/.test(metric || "")) return `${number(numeric * 1000, numeric * 1000 < 10 ? 2 : 1)} mCPU`;
  return number(numeric);
}
function baselineDelta(item) {
  const current = Number(item.current), baseline = Number(item.baseline);
  return Number.isFinite(current) && Number.isFinite(baseline) && baseline !== 0 ? (current - baseline) / Math.abs(baseline) : null;
}
function anomalyScoreQuality(item) {
  const zScore = Math.abs(Number(item.zScore));
  const relative = Math.abs(baselineDelta(item) || 0);
  const dispersion = Number(item.raw?.baseline?.standard_deviation);
  return zScore > 100 && relative < 1 && (!Number.isFinite(dispersion) || dispersion / Math.max(Math.abs(Number(item.baseline)), 1) < 0.01);
}
function anomalyIsNonActionableSignal(item) {
  const metric = String(item.metric || "");
  const current = Math.abs(Number(item.current) || 0);
  const baseline = Math.abs(Number(item.baseline) || 0);
  // 무트래픽 서비스는 기준선도 0이다. 이 상태에서 0을 다시 관측한 것은
  // 서비스 장애가 아니라 평가 대상이 없는 것이므로 조사 큐에서 제외한다.
  if (metric === "service_request_rate" && Math.max(current, baseline) < 0.001) return true;
  // CPU 사용량이 50m 미만인 Pod의 몇 mCPU 변동은 실제 사용자 영향으로
  // 해석할 수 없다. 오류/Trace/Incident 근거가 있을 때만 예외로 조사한다.
  if (metric === "pod_cpu_usage" && Math.max(current, baseline) < 0.05) return true;
  return false;
}
function anomalyHasCorroboration(item) {
  const service = serviceIdentity(item.service);
  const detectedAt = new Date(item.evaluatedAt);
  const near = (value, minutes = 15) => {
    const at = new Date(value);
    return !Number.isNaN(at.getTime()) && !Number.isNaN(detectedAt.getTime()) && Math.abs(at - detectedAt) <= minutes * 60 * 1000;
  };
  const logEvidence = rawLogRows(dashboard.issueLogs || []).some((row) => row.service.includes(service) && near(row.time));
  const traceEvidence = (dashboard.errorTraces || []).some((row) => traceDisplayService(row) === service && near(traceStartedAt(row)));
  const incidentEvidence = (dashboard.incidents || []).some((row) => (row.affected_services || []).some((name) => String(name).includes(service)) && (near(row.first_seen_at, 30) || near(row.last_seen_at, 30)));
  return logEvidence || traceEvidence || incidentEvidence;
}
function anomalyPriorityItems() {
  const episodes = new Map();
  scopedAnomalies().forEach((item) => {
    const key = `${item.status}:${item.service}:${item.metric}`;
    const episode = episodes.get(key) || { ...item, id: key, observations: 0, firstEvaluatedAt: item.evaluatedAt };
    episode.observations += 1;
    if (new Date(item.evaluatedAt) > new Date(episode.evaluatedAt)) Object.assign(episode, item, { id: key, observations: episode.observations, firstEvaluatedAt: episode.firstEvaluatedAt });
    if (new Date(item.evaluatedAt) < new Date(episode.firstEvaluatedAt)) episode.firstEvaluatedAt = item.evaluatedAt;
    episodes.set(key, episode);
  });
  return [...episodes.values()].sort((a, b) => {
    const severity = { critical: 2, anomaly: 1, warning: 1 };
    const bySeverity = (severity[tone(b.status)] || 0) - (severity[tone(a.status)] || 0);
    if (bySeverity) return bySeverity;
    const byScore = Math.abs(Number(b.zScore) || 0) - Math.abs(Number(a.zScore) || 0);
    if (byScore) return byScore;
    return new Date(b.evaluatedAt) - new Date(a.evaluatedAt);
  });
}
function selectedAnomaly() {
  const items = actionableAnomalyItems();
  const selected = items.find((item) => item.id === selectedAnomalyId) || items[0] || null;
  selectedAnomalyId = selected?.id || "";
  return selected;
}
function actionableAnomalyItems() {
  return anomalyPriorityItems().filter((item) => {
    const corroborated = anomalyHasCorroboration(item);
    // candidate는 Analyzer의 3회 연속 확정 전 관찰값이다. 독립 근거가 없으면
    // 운영자의 조사 큐가 아니라 재보정/관찰 영역에 남긴다.
    if (item.status !== "anomaly" && !corroborated) return false;
    // 0 RPS/0 기준선, 수 mCPU 수준의 변동은 Collector의 평가 레코드일 뿐
    // 단독으로 운영 조사가 필요한 이상징후가 아니다.
    if (anomalyIsNonActionableSignal(item) && !corroborated) return false;
    if (anomalyScoreQuality(item) && !corroborated) return false;
    // Pod 자원은 매우 작은 정상 변동에도 분산이 작으면 점수가 커진다. 화면의
    // 조사 큐에서는 기준선 대비 15% 이상이거나 독립 근거가 있는 경우만 올린다.
    if (/^pod_(cpu_usage|memory_working_set)$/.test(item.metric) && Math.abs(baselineDelta(item) || 0) < 0.15 && !corroborated) return false;
    return true;
  });
}
function anomalyPriorityPanel() {
  const allItems = anomalyPriorityItems();
  if (!allItems.length) return empty("실제 anomaly 없음", "선택 기간에 Analyzer가 저장한 candidate/anomaly가 없습니다.");
  const items = actionableAnomalyItems();
  const recalibration = allItems.length - items.length;
  const selected = selectedAnomaly();
  const rows = items.length ? items.map((item) => { const delta = baselineDelta(item); const scoreWarning = anomalyScoreQuality(item); return `<tr class="anomaly-row ${item.id === selected?.id ? "selected" : ""}" data-anomaly-id="${escapeHtml(item.id)}"><td><span class="status ${tone(item.status)}">${text(item.status)}</span></td><td><strong>${text(item.service)}</strong></td><td>${text(item.metric)}</td><td>${anomalyValue(item.current, item.metric)}</td><td>${anomalyValue(item.baseline, item.metric)}</td><td class="${delta > 0 ? "warning-text" : ""}">${delta == null ? "-" : `${delta >= 0 ? "+" : ""}${number(delta * 100, 1)}%`}</td><td>${item.change == null ? "-" : `${number(item.change * 100, 1)}%`}</td><td>${scoreWarning ? `<span class="score-caution">분산 과소</span>` : `Z ${number(item.zScore, 2)}`}</td><td>${number(item.observations, 0)}회</td><td>${date(item.evaluatedAt)}</td></tr>`; }).join("") : `<tr><td colspan="10" class="anomaly-empty-row">즉시 조사할 anomaly 없음 — ${recalibration}개 에피소드는 candidate, 미세 자원 변동 또는 기준선 분산 과소라 재보정 관찰로 분리했습니다.</td></tr>`;
  return `<section class="table-panel anomaly-priority-panel"><header><div><p>AI ANOMALY QUEUE</p><h2>조사 우선순위</h2><span>확정 anomaly만 기본 표시합니다. Pod CPU·메모리는 기준선 대비 15% 이상이거나 로그·오류 Trace·Incident 근거가 있을 때만 조사 대상으로 올립니다.</span></div><span>${items.length} INVESTIGATE${recalibration ? ` · ${recalibration} OBSERVE` : ""}</span></header><div class="table-wrap"><table><thead><tr><th>상태</th><th>대상</th><th>지표</th><th>현재값</th><th>기준선</th><th>기준선 대비</th><th>직전 대비</th><th>점수 상태</th><th>발생</th><th>최근 탐지</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}
function anomalyTrendPanel() {
  const candidates = scopedAnomalies();
  if (!candidates.length) return `<section class="hero-panel"><header><div><p>AI ANOMALY DETECTION</p><h2>기준선 이탈 추이</h2></div>${sourceState("operations_db")}</header><div class="no-chart">선택 기간에 실제 anomaly가 없습니다.</div></section>`;
  const latest = selectedAnomaly();
  if (!latest) return `<section class="hero-panel"><header><div><p>AI ANOMALY DETECTION</p><h2>즉시 조사할 anomaly 없음</h2></div>${sourceState("operations_db")}</header><div class="no-chart">현재 탐지는 기준선 분산 과소로 인한 재보정 관찰 항목입니다.<br><small>독립 로그·오류 Trace·Incident 근거가 생기면 조사 우선순위에 표시됩니다.</small></div></section>`;
  const related = candidates
    .filter((item) => item.service === latest.service && item.metric === latest.metric)
    .slice()
    .sort((a, b) => new Date(a.evaluatedAt) - new Date(b.evaluatedAt));
  const actual = { metric: { service: "실제값" }, values: related.map((item) => [new Date(item.evaluatedAt).getTime() / 1000, item.current]) };
  const baseline = { metric: { service: "정상 기준선" }, values: related.map((item) => [new Date(item.evaluatedAt).getTime() / 1000, item.baseline]) };
  const relative = baselineDelta(latest);
  return `<section class="hero-panel anomaly-trend-panel"><header><div><p>AI ANOMALY DETECTION</p><h2>${text(latest.service)} · ${text(latest.metric)}</h2><span>실제값과 Collector가 저장한 기준선을 비교합니다. 기준선 대비 ${relative == null ? "-" : `${relative >= 0 ? "+" : ""}${number(relative * 100, 1)}%`} · 직전 대비 ${latest.change == null ? "-" : `${number(latest.change * 100, 1)}%`}</span></div>${sourceState("operations_db")}</header>${lineChart([actual, baseline], (value) => anomalyValue(value, latest.metric))}<footer><span>최근 ${related.length}개 탐지 레코드</span><span>${anomalyScoreQuality(latest) ? "분산 과소로 Z-score 과대 가능" : `Z-score ${number(latest.zScore, 2)}`} · ${date(latest.evaluatedAt)}</span></footer></section>`;
}
function renderOverviewBanner() {
  const banner = $("#overviewBanner");
  if (activeView !== "overview") {
    banner.hidden = true;
    banner.innerHTML = "";
    return;
  }
  banner.hidden = false;
  banner.innerHTML = `<p>OPERATIONS OVERVIEW</p>`;
}
function summaryCards() {
  const summary = dashboard.summary || {};
  const ov = dashboard.overview || {};
  const hasIncident = Number(summary.incident_count ?? dashboard.incidents.length) > 0;
  const investigate = actionableAnomalyItems().length;
  const overviewCards = [
    ["SYSTEM STATUS", hasIncident ? "ACTION REQUIRED" : "HEALTHY", hasIncident ? "critical" : "normal", "LIVE · Operations"],
    ["OPEN INCIDENTS", number(summary.incident_count ?? dashboard.incidents.length, 0), hasIncident ? "critical" : "normal", "LIVE · Operations DB"],
    ["INVESTIGATE", number(investigate, 0), investigate ? "warning" : "normal", "Qualified anomaly episodes"],
    ["API RPS", ov.rps != null ? number(ov.rps, 2) : "-", "neutral", "LIVE · Prometheus"],
    ["ERROR RATE", ov.errorRatePercent != null ? `${number(ov.errorRatePercent, 2)}%` : "-", ov.errorRatePercent > 0 ? "warning" : "normal", "LIVE · Istio"],
    ["P95 LATENCY", ov.p95Ms != null ? `${number(ov.p95Ms, 0)} ms` : "-", "neutral", "LIVE · Prometheus"],
  ];
  const isOverview = activeView === "overview";
  $("#summaryCards").classList.toggle("overview-summary", isOverview);
  $("#summaryCards").hidden = !isOverview;
  $("#summaryCards").innerHTML = isOverview ? overviewCards.map(([label, value, color, detail]) => `<article><small>${label}</small><strong class="${color}">${value}</strong><span>${detail || "실제 Operations 데이터"}</span></article>`).join("") : "";
  $("#navAnomalyCount").textContent = number(summary.anomaly_count ?? dashboard.anomalies.length, 0);
  $("#navIncidentCount").textContent = number(summary.incident_count ?? dashboard.incidents.length, 0);
  $("#navServiceCount").textContent = number(serviceCatalogRows().length, 0);
}
function incidentPanel() { const incidents = dashboard.incidents || []; return `<section class="incident-panel"><header><p>AI INVESTIGATION</p><h2>활성 Incident</h2></header>${incidents.length ? incidents.slice(0, 3).map((item) => `<article><span class="status ${tone(item.status)}">${text(item.status)}</span><h3>${text(item.title, "제목 없는 Incident")}</h3><p>${(item.affected_services || []).join(" · ") || "영향 서비스 미분류"}</p><small>Alert ${number(item.alert_count, 0)}개 · ${date(item.first_seen_at)}</small></article>`).join("") : `<article><h3>활성 Incident 없음</h3><p>관련 Alert가 묶이면 이곳에서 조사합니다.</p></article>`}</section>`; }
function sparkline(pairs, color = "#6366f1", height = 40) {
  if (!pairs || !pairs.length) return `<div class="spark-empty">데이터 없음</div>`;
  const width = 220, pad = 4, axisH = 12;
  const nums = pairs.map(([, v]) => Number(v)).filter((v) => Number.isFinite(v));
  if (!nums.length) return `<div class="spark-empty">데이터 없음</div>`;
  const min = Math.min(...nums);
  const max = Math.max(...nums, min + 0.001);
  const span = max - min || 1;
  const chartH = height - axisH;
  const y = (v) => chartH - pad - ((v - min) / span) * (chartH - pad * 2);
  const firstTime = Number(pairs[0][0]);
  const lastTime = Number(pairs[pairs.length - 1][0]);
  const timeSpan = Math.max(lastTime - firstTime, 1);
  const x = (timestamp) => ((Number(timestamp) - firstTime) / timeSpan) * width;
  const pts = pairs.map(([timestamp, v]) => `${x(timestamp)},${y(Number(v))}`).join(" ");
  const lastY = y(nums[nums.length - 1]);
  const ticks = [0, .5, 1].map((fraction) => {
    const timestamp = firstTime + timeSpan * fraction;
    return { x: width * fraction, label: chartTime(timestamp, firstTime, lastTime) };
  });
  return `<svg viewBox="0 0 ${width} ${height}" class="sparkline" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${color}" />${pairs.map(([timestamp, value]) => `<circle class="chart-hover-point" cx="${x(timestamp)}" cy="${y(Number(value))}" r="4"><title>${fullChartTime(timestamp)} · ${number(value)}</title></circle>`).join("")}<circle cx="${width}" cy="${lastY}" r="2.8" fill="${color}" />${ticks.map((tick) => `<text x="${tick.x}" y="${height - 1}" class="spark-axis-label" text-anchor="${tick.x === 0 ? "start" : tick.x === width ? "end" : "middle"}">${tick.label}</text>`).join("")}</svg>`;
}
function overviewKpis() {
  const ov = dashboard.overview || {};
  const rpsSeries = dashboard.rpsTimeseries?.[0]?.values || [];
  const errorSeries = dashboard.errorRateTimeseries?.[0]?.values || [];
  const p95Series = dashboard.p95Timeseries?.[0]?.values || [];
  const cards = [
    ["전체 RPS", ov.rps != null ? number(ov.rps, 2) : "-", rpsSeries, "#6366f1"],
    ["5xx 비율", ov.errorRatePercent != null ? `${number(ov.errorRatePercent, 2)}%` : "-", errorSeries, "#ef4444"],
    ["p95 지연", ov.p95Ms != null ? `${number(ov.p95Ms, 0)}ms` : "-", p95Series, "#f59e0b"],
  ];
  const incidentCount = (dashboard.incidents || []).length;
  return `<section class="kpi-trend-cards">${cards.map(([label, value, series, color]) => `<article class="kpi-trend-card"><header><small>${label}</small><strong>${value}</strong></header>${sparkline(series, color)}<span>실제 Prometheus · 선택 기간 추이</span></article>`).join("")}<article class="kpi-trend-card kpi-trend-static"><header><small>활성 Incident</small><strong class="${incidentCount ? "critical" : ""}">${number(incidentCount, 0)}</strong></header><div class="kpi-static-note">${incidentCount ? "조사 중인 Incident가 있습니다" : "정상 · 조사 중인 Incident 없음"}</div><span>실제 Operations 데이터</span></article></section>`;
}
function redTrendPanel() {
  const rows = [
    ["요청량 (RPS)", dashboard.rpsTimeseries?.[0]?.values || [], "#6366f1", (v) => number(v, 2)],
    ["오류율 (5xx %)", dashboard.errorRateTimeseries?.[0]?.values || [], "#ef4444", (v) => `${number(v, 2)}%`],
    ["p95 지연 (ms)", dashboard.p95Timeseries?.[0]?.values || [], "#f59e0b", (v) => `${number(v, 0)}ms`],
  ];
  return `<article class="dashboard-panel red-trend-panel"><header><div><h3>RED 추이 · 전체 서비스 집계</h3><p>실제 Prometheus · Rate / Error / Duration을 같은 시간축에서 비교 · 서비스별 세부는 Metrics·Services 탭</p></div>${sourceState("prometheus")}</header>${rows.map(([label, values, color, format]) => {
    const last = values.length ? Number(values[values.length - 1][1]) : null;
    return `<div class="red-trend-row"><div class="red-trend-label"><span style="--c:${color}">${label}</span><strong>${last == null || Number.isNaN(last) ? "-" : format(last)}</strong></div>${sparkline(values, color, 46)}</div>`;
  }).join("")}</article>`;
}
function miniBar(value, max, digits = 2, suffix = "") {
  const v = Number(value);
  if (!Number.isFinite(v)) return `<span class="mini-bar-cell"><em>-</em></span>`;
  const pct = max > 0 ? Math.max(v > 0 ? 3 : 0, Math.min(100, (v / max) * 100)) : 0;
  return `<span class="mini-bar-cell"><span class="mini-bar-track"><i style="width:${pct}%"></i></span><em>${number(v, digits)}${suffix}</em></span>`;
}
function serviceHealthSummaryPanel() {
  // Atatus의 Endpoints 표(칸 안에 미니바) 참고 — 카탈로그처럼 항목이 많은 목록은
  // 카드 반복이 아니라 표 + 인라인 바로 압축해서 한눈에 훑을 수 있게 한다.
  const rows = serviceCatalogRows();
  const maxRps = Math.max(...rows.map((row) => row.rps || 0), 0.001);
  const p95MsList = rows.map((row) => (Number.isFinite(Number(row.p95)) ? Number(row.p95) * 1000 : null));
  const maxP95 = Math.max(...p95MsList.filter((v) => v != null), 0.001);
  const maxAnomaly = Math.max(...rows.map((row) => row.anomalyCount || 0), 1);
  return `<article class="dashboard-panel service-health-panel"><header><div><h3>서비스 건강도 (${rows.length}개)</h3><p>전체 카탈로그 요약 · 상세 지표는 Services / APM</p></div>${sourceState("prometheus")}</header><div class="table-wrap"><table class="mini-bar-table"><thead><tr><th>서비스</th><th>상태</th><th>RPS</th><th>p95 (ms)</th><th>탐지 레코드</th></tr></thead><tbody>${rows.map((row, index) => `<tr><td><strong>${text(row.name)}</strong></td><td><span class="status ${row.statusTone}">${row.statusLabel}</span></td><td>${row.rps == null ? `<span class="mini-bar-cell"><em>대기</em></span>` : miniBar(row.rps, maxRps)}</td><td>${p95MsList[index] == null ? `<span class="mini-bar-cell"><em>-</em></span>` : miniBar(p95MsList[index], maxP95, 0)}</td><td>${miniBar(row.anomalyCount, maxAnomaly, 0)}</td></tr>`).join("")}</tbody></table></div></article>`;
}
function infraQuickStatsPanel() {
  // 올리브영 "서버 현황" 컬럼처럼 작은 타일 여러 개 — 단, Top N 순위(누가 1등인지)는
  // Metrics 탭 소관이라 여기서는 "지금 봐야 하나?"만 판단할 수 있는 합계/최댓값만 보여준다.
  const restarts = (dashboard.podRestarts || []).filter((item) => Number(item.value[1]) > 0);
  const totalRestarts = restarts.reduce((sum, item) => sum + Number(item.value[1]), 0);
  const lag = dashboard.kafkaLag || [];
  const maxLag = lag.length ? Math.max(...lag.map((item) => Number(item.value[1]))) : null;
  const net = dashboard.networkIO || [];
  const totalNetBytes = net.length ? net.reduce((sum, item) => sum + Number(item.value[1]), 0) : null;
  const tiles = [
    ["Pod 재시작 (1시간)", `${number(totalRestarts, 0)}회`, totalRestarts > 0 ? "warning" : "normal"],
    ["Kafka 최대 Lag", maxLag == null ? "-" : `${number(maxLag, 0)}건`, maxLag != null && maxLag > 100 ? "warning" : "normal"],
    ["Pod 네트워크 송신 합", totalNetBytes == null ? "-" : `${number(totalNetBytes / 1024 / 1024, 2)} MiB/s`, "normal"],
  ];
  return `<div class="infra-quick-stats">${tiles.map(([label, value, toneName]) => `<article><small>${label}</small><strong class="${toneName}">${value}</strong></article>`).join("")}</div>`;
}
function overviewAttentionPanel() {
  const incidents = dashboard.incidents || [];
  const anomalyGroups = groupedAnomalyEvents().slice(0, 2);
  const deployments = (dashboard.deployEvents || []).slice(0, 1);
  const items = [];
  if (incidents.length) {
    const incident = incidents[0];
    items.push(["critical", "Incident", text(incident.title, "제목 없는 Incident"), (incident.affected_services || []).join(" · ") || "영향 서비스 미분류", "incidents", "Incident 열기"]);
  }
  if (anomalyGroups.length) {
    const group = anomalyGroups[0];
    items.push([group.critical ? "critical" : "warning", "AI 탐지", `${group.total}건 · ${group.services.size}개 서비스`, [...group.metrics].slice(0, 2).join(" · ") || "측정 지표 미분류", "anomalies", "탐지 보기"]);
  }
  if (deployments.length) {
    const deployment = deployments[0];
    items.push(["normal", "최근 배포", `${text(deployment.namespace)}/${text(deployment.deployment)}`, date(deployment.created_at), "events", "Events 열기"]);
  }
  if (!items.length) {
    return `<article class="dashboard-panel overview-attention"><header><div><p>INVESTIGATION QUEUE</p><h3>지금 조사할 대상</h3><span>Incident · AI 탐지 · 플랫폼 이벤트를 한 곳에서 우선순위화합니다.</span></div></header><div class="panel-empty">현재 우선 조사 대상이 없습니다.</div></article>`;
  }
  return `<article class="dashboard-panel overview-attention"><header><div><p>INVESTIGATION QUEUE</p><h3>지금 조사할 대상</h3><span>Incident · AI 탐지 · 플랫폼 이벤트를 한 곳에서 우선순위화합니다.</span></div></header><div class="attention-list">${items.map(([status, kind, title, detail, view, action]) => `<article><i class="${status}"></i><div><small>${kind}</small><strong>${title}</strong><span>${detail}</span></div><button type="button" data-open-view="${view}">${action}</button></article>`).join("")}</div><footer><span>Bedrock RCA: Evidence Snapshot 준비됨 · 아직 미연동</span></footer></article>`;
}
function overviewServiceRiskPanel() {
  const rows = serviceCatalogRows()
    .filter((row) => row.incidentCount || row.anomalyCount || row.error > 0 || row.rps > 0 || Number(row.p95) > 0)
    .map((row) => ({ ...row, risk: row.incidentCount * 100000 + row.error * 10000 + (Number(row.p95) || 0) * 100 + row.anomalyCount }))
    .sort((a, b) => b.risk - a.risk)
    .slice(0, 5);
  if (!rows.length) return `<article class="dashboard-panel overview-risk"><header><div><h3>서비스 위험 Top 5</h3><p>Incident · 5xx · p95 · AI 탐지 신호가 있는 서비스만 표시합니다.</p></div><button type="button" data-open-view="services">Services / APM</button></header><div class="panel-empty">선택 기간에 우선 조사할 서비스 신호가 없습니다.</div></article>`;
  return `<article class="dashboard-panel overview-risk"><header><div><h3>서비스 위험 Top 5</h3><p>활성 Incident → 5xx → p95 → AI 탐지 레코드 순으로 우선순위를 정렬합니다.</p></div><button type="button" data-open-view="services">Services / APM</button></header><div class="table-wrap"><table class="overview-risk-table"><thead><tr><th>서비스</th><th>상태</th><th>RPS</th><th>p95</th><th>5xx</th><th>탐지</th></tr></thead><tbody>${rows.map((row) => `<tr><td><strong>${text(row.name)}</strong></td><td><span class="status ${row.statusTone}">${row.statusLabel}</span></td><td>${row.rps == null ? "-" : `${number(row.rps, 3)}`}</td><td>${row.p95 == null ? "-" : `${number(Number(row.p95) * 1000, 0)} ms`}</td><td class="${row.error ? "critical-text" : ""}">${number(row.error, 3)}</td><td>${number(row.anomalyCount, 0)}</td></tr>`).join("")}</tbody></table></div></article>`;
}
function overviewErrorLogPreviewPanel() {
  const rows = logRows().slice(0, 5);
  if (!rows.length) return `<article class="dashboard-panel overview-preview"><header><div><h3>최근 오류 로그</h3><p>실제 Loki · app/data/pipeline namespace · 최근 5건</p></div>${sourceState("loki")}</header><div class="panel-empty">선택 기간에 오류 로그가 없습니다.</div></article>`;
  return `<article class="dashboard-panel overview-preview"><header><div><h3>최근 오류 로그</h3><p>실제 Loki · app/data/pipeline namespace · 최근 5건</p></div>${sourceState("loki")}</header><div class="overview-preview-list">${rows.map((row) => `<article><time>${date(row.time)}</time><strong>${text(row.service)}</strong><span title="${text(row.line)}">${text(row.line)}</span></article>`).join("")}</div><footer><button type="button" data-open-view="logs">Logs 탐색</button></footer></article>`;
}
function overviewTracePreviewPanel() {
  const traces = (dashboard.recentTraces || []).filter((item) => selectedService() === "all" || item.rootServiceName === selectedService());
  const errors = (dashboard.errorTraces || []).filter((item) => selectedService() === "all" || item.rootServiceName === selectedService());
  const slowest = [...traces].sort((a, b) => Number(b.durationMs) - Number(a.durationMs)).slice(0, 3);
  if (!traces.length && !errors.length) return `<article class="dashboard-panel overview-preview"><header><div><h3>오류 · 느린 Trace</h3><p>실제 Tempo 검색 결과 · 오류와 응답 지연 조사</p></div>${sourceState("tempo")}</header><div class="panel-empty">선택 기간에 조회된 Trace가 없습니다.</div></article>`;
  return `<article class="dashboard-panel overview-preview"><header><div><h3>오류 · 느린 Trace</h3><p>오류 ${errors.length}건 · 조회 Trace ${traces.length}건 · 느린 요청 상위 3개</p></div>${sourceState("tempo")}</header><div class="overview-preview-list">${slowest.map((item) => `<article><time>${number(item.durationMs, 0)} ms</time><strong>${text(item.rootServiceName)}</strong><span>${text(item.rootTraceName, "/")}</span></article>`).join("")}</div><footer><button type="button" data-open-view="traces">Traces 탐색</button></footer></article>`;
}
function apmDemoPanel() {
  const metrics = [["API p95", "184 ms", "#635bdf"], ["5xx 오류율", "0.21%", "#df5b69"], ["가용성", "99.98%", "#159570"], ["처리량", "62 req/s", "#2878d4"]];
  return `<article class="dashboard-panel wide apm-demo-panel"><header><div><h3>APM 성능 요약</h3><p>RPS·지연·오류·가용성은 실제 APM 계측 후 이 자리에서 서비스별 실데이터로 교체됩니다.</p></div><span class="source-state waiting">DEMO · APM 계측 보강 예정</span></header><div class="apm-demo-metrics">${metrics.map(([label, value, color]) => `<div><small>${label}</small><strong style="--apm-color:${color}">${value}</strong><span>예시 데이터</span></div>`).join("")}</div></article>`;
}
function overview() {
  const infraStats = source("prometheus").enabled ? infraQuickStatsPanel() : "";
  const hasRestart = (dashboard.podRestarts || []).some((item) => Number(item.value[1]) > 0);
  const hasLogs = logRows().length > 0;
  const hasTraces = (dashboard.recentTraces || []).length > 0 || (dashboard.errorTraces || []).length > 0;
  return `<section class="overview-domain-grid">
      <section class="overview-domain server-domain"><section class="overview-section-banner platform-section"><p>INFRASTRUCTURE</p></section><section class="server-dashboard-grid">${source("prometheus").enabled ? serverResourceStatusPanel() : panel("노드 자원 사용 상태", "Node CPU·메모리·디스크 사용률", "prometheus", "wide")}${source("prometheus").enabled ? resourceTopPanel() : panel("Pod CPU·메모리 사용량", "Pod별 컨테이너 자원 사용량", "prometheus", "wide")}${hasRestart ? podRestartPanel() : ""}<div class="overview-platform-stats">${infraStats || `<div class="panel-empty">Prometheus 연결 시 인프라 요약이 표시됩니다.</div>`}</div></section></section>
      <section class="overview-domain application-domain"><section class="overview-section-banner application-section"><p>APPLICATION PERFORMANCE</p></section><section class="application-dashboard-grid">${redTrendPanel()}${hasLogs ? overviewErrorLogPreviewPanel() : ""}${hasTraces ? overviewTracePreviewPanel() : ""}</section></section>
    </section>
    <section class="overview-section-banner summary-section"><p>OPERATIONS INTELLIGENCE</p></section>
    <section class="application-summary-grid">${overviewServiceRiskPanel()}${overviewAttentionPanel()}</section>`;
}
function anomalyTable(items = dashboard.anomalies) { if (!items.length) return empty("실제 anomaly 없음", "선택 범위에서 Collector가 저장한 anomaly가 없습니다."); return `<section class="table-panel"><header><div><p>ANOMALY QUEUE</p><h2>조사 우선순위</h2></div><span>${items.length} RESULTS</span></header><table><thead><tr><th>상태</th><th>서비스</th><th>지표</th><th>현재값</th><th>기준선</th><th>Z-score</th><th>변화율</th><th>시각</th></tr></thead><tbody>${items.map((item) => `<tr><td><span class="status ${tone(item.status)}">${text(item.status)}</span></td><td><strong>${text(item.service)}</strong></td><td>${text(item.metric)}</td><td>${number(item.current)}</td><td>${number(item.baseline)}</td><td>${number(item.zScore)}</td><td>${item.change === null || item.change === undefined ? "-" : `${number(item.change * 100, 1)}%`}</td><td>${date(item.evaluatedAt)}</td></tr>`).join("")}</tbody></table></section>`; }
function sourcePage(name, title, detail) { const state = source(name); return `<section class="explorer-layout"><header><div><p>${title}</p><h2>${state.enabled ? "실데이터 탐색" : "데이터 소스 연결 필요"}</h2><span>${detail}</span></div>${sourceState(name)}</header>${state.enabled ? `<div class="query-panel"><h3>조회 결과는 Dashboard Proxy가 실제 ${title}에서 읽어 표시합니다.</h3><p>현재 프론트는 임의의 로그·Trace·시계열을 만들지 않습니다.</p></div>` : `<div class="query-panel"><h3>가짜 패널을 표시하지 않습니다.</h3><p>${title} URL과 읽기 권한을 로컬 Proxy에 설정하면 이 화면에 실제 결과가 표시됩니다.</p></div>`}</section>`; }
function panel(title, description, sourceName, size = "") { return `<article class="dashboard-panel ${size}"><header><div><h3>${title}</h3><p>${description}</p></div>${sourceState(sourceName)}</header><div class="panel-empty">이 탐색 화면은 다음 단계에서 구현됩니다.<br><small>연결 여부와 별개로 임의 데이터를 표시하지 않습니다.</small></div></article>`; }
const CHART_COLORS = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#a855f7", "#84cc16", "#ec4899", "#14b8a6", "#f97316"];
function seriesName(metric = {}) { return metric.service || metric.destination_service_name || metric.host || metric.pod || metric.instance || "unknown"; }
function lineChart(series, formatValue = (value) => number(value, 2), options = {}) {
  // Prometheus histogram_quantile은 bucket이 비는 구간에 NaN을 섞어 보낼 수 있다.
  // polyline 좌표 하나라도 NaN이면 브라우저가 선 전체를 그리지 않으므로, 렌더 전에 제거한다.
  const validSeries = (series || []).map((item) => ({
    ...item,
    values: (item.values || []).filter(([timestamp, value]) => Number.isFinite(Number(timestamp)) && Number.isFinite(Number(value))),
  })).filter((item) => item.values.length);
  if (!validSeries.length) return `<div class="no-chart">쿼리 결과가 없습니다.</div>`;
  const width = 840, height = 270, left = 58, right = 16, top = 14, bottom = 34;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const allValues = validSeries.flatMap((item) => item.values.map(([, value]) => Number(value)).filter(Number.isFinite));
  const allTimes = validSeries.flatMap((item) => item.values.map(([timestamp]) => Number(timestamp)).filter(Number.isFinite));
  if (!allValues.length || !allTimes.length) return `<div class="no-chart">유효한 시계열 값이 없습니다.</div>`;
  const rawMin = Math.min(...allValues);
  const rawMax = Math.max(...allValues);
  const padding = Math.max((rawMax - rawMin) * .08, Math.abs(rawMax) * .02, .001);
  const min = options.baselineZero === false ? rawMin - padding : Math.min(0, rawMin - padding);
  const max = Math.max(rawMax + padding, min + 0.001);
  const span = max - min || 1;
  const y = (value) => top + plotHeight - ((Number(value) - min) / span) * plotHeight;
  const firstTime = Math.min(...allTimes);
  const lastTime = Math.max(...allTimes);
  const timeSpan = Math.max(lastTime - firstTime, 1);
  const x = (timestamp) => left + ((Number(timestamp) - firstTime) / timeSpan) * plotWidth;
  const points = (values) => values.map(([timestamp, value]) => `${x(timestamp)},${y(value)}`).join(" ");
  const ticks = Array.from({ length: 5 }, (_, index) => {
    const fraction = index / 4;
    const timestamp = firstTime + timeSpan * fraction;
    return { x: left + plotWidth * fraction, label: chartTime(timestamp, firstTime, lastTime) };
  });
  const yTicks = Array.from({ length: 5 }, (_, index) => {
    const fraction = index / 4;
    return { y: top + plotHeight * (1 - fraction), value: min + span * fraction };
  });
  const verticalGrid = ticks.map((tick) => `<line x1="${tick.x}" y1="${top}" x2="${tick.x}" y2="${top + plotHeight}" class="chart-grid-line" />`).join("");
  const horizontalGrid = yTicks.map((tick) => `<line x1="${left}" y1="${tick.y}" x2="${left + plotWidth}" y2="${tick.y}" class="chart-grid-line" /><text x="${left - 7}" y="${tick.y + 3}" class="axis-label" text-anchor="end">${formatValue(tick.value)}</text>`).join("");
  const legend = validSeries.map((item, index) => {
    const values = item.values.map(([, value]) => Number(value)).filter(Number.isFinite);
    const last = values.at(-1);
    const peak = Math.max(...values);
    return `<tr><td><span class="legend-color" style="--c:${CHART_COLORS[index % CHART_COLORS.length]}"></span>${text(seriesName(item.metric), "unknown")}</td><td>${formatValue(last)}</td><td>${formatValue(peak)}</td></tr>`;
  }).join("");
  return `<div class="grafana-timeseries"><svg viewBox="0 0 ${width} ${height}" class="line-chart" preserveAspectRatio="none">${verticalGrid}${horizontalGrid}${validSeries.map((item, index) => `<polyline points="${points(item.values)}" fill="none" style="stroke:${CHART_COLORS[index % CHART_COLORS.length]}" />${item.values.length <= 8 ? item.values.map(([timestamp, value]) => `<circle class="chart-value-point" cx="${x(timestamp)}" cy="${y(value)}" r="2.6" fill="${CHART_COLORS[index % CHART_COLORS.length]}" />`).join("") : ""}${item.values.map(([timestamp, value]) => `<circle class="chart-hover-point" cx="${x(timestamp)}" cy="${y(value)}" r="6" data-time="${timestamp}" data-series="${index}" data-label="${text(seriesName(item.metric), "series")}" data-display="${formatValue(value)}" data-color="${CHART_COLORS[index % CHART_COLORS.length]}" />`).join("")}`).join("")}<line x1="${left}" y1="${top + plotHeight}" x2="${left + plotWidth}" y2="${top + plotHeight}" class="axis-line" />${ticks.map((tick) => `<text x="${tick.x}" y="${height - 8}" class="axis-label" text-anchor="middle">${tick.label}</text>`).join("")}</svg><div class="chart-shared-tooltip" hidden></div><div class="timeseries-legend"><table><thead><tr><th>Name</th><th>Last</th><th>Max</th></tr></thead><tbody>${legend}</tbody></table></div></div>`;
}
function attachSharedChartTooltips() {
  document.querySelectorAll(".grafana-timeseries").forEach((container) => {
    const svg = container.querySelector(".line-chart");
    const tooltip = container.querySelector(".chart-shared-tooltip");
    const points = [...container.querySelectorAll(".chart-hover-point")];
    if (!svg || !tooltip || !points.length) return;
    const hide = () => { tooltip.hidden = true; };
    svg.addEventListener("mouseleave", hide);
    svg.addEventListener("mousemove", (event) => {
      const bounds = svg.getBoundingClientRect();
      const chartX = ((event.clientX - bounds.left) / bounds.width) * 840;
      const nearest = points.reduce((best, point) => Math.abs(Number(point.getAttribute("cx")) - chartX) < Math.abs(Number(best.getAttribute("cx")) - chartX) ? point : best, points[0]);
      const selectedTime = Number(nearest.dataset.time);
      const rows = new Map();
      points.forEach((point) => {
        const current = rows.get(point.dataset.series);
        if (!current || Math.abs(Number(point.dataset.time) - selectedTime) < Math.abs(Number(current.dataset.time) - selectedTime)) rows.set(point.dataset.series, point);
      });
      tooltip.innerHTML = `<strong>${fullChartTime(selectedTime)}</strong>${[...rows.values()].map((point) => `<span><i style="--c:${point.dataset.color}"></i>${text(point.dataset.label)}<b>${text(point.dataset.display)}</b></span>`).join("")}`;
      const containerBounds = container.getBoundingClientRect();
      const tooltipWidth = 230;
      const left = Math.max(8, Math.min(event.clientX - containerBounds.left + 14, containerBounds.width - tooltipWidth - 8));
      const top = Math.max(8, event.clientY - containerBounds.top + 14);
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
      tooltip.hidden = false;
    });
  });
}
function topBars(items, labelFn, valueFn, formatFn = (value) => number(value)) {
  if (!items.length) return `<div class="no-chart">쿼리 결과가 없습니다.</div>`;
  const max = Math.max(...items.map(valueFn), 0.001);
  return `<div class="top-bars">${items.map((item) => `<div class="top-bar-row"><span class="top-bar-label">${labelFn(item)}</span><div class="top-bar-track"><i style="width:${Math.max(4, (valueFn(item) / max) * 100)}%"></i></div><span class="top-bar-value">${formatFn(valueFn(item))}</span></div>`).join("")}</div>`;
}
function donutChart(items, labelFn, valueFn) {
  const total = items.reduce((sum, item) => sum + valueFn(item), 0);
  if (!items.length || total <= 0) return `<div class="no-chart">데이터 없음(전체 0)</div>`;
  const radius = 52, circumference = 2 * Math.PI * radius;
  let offset = 0;
  const arcs = items.map((item, index) => {
    const fraction = valueFn(item) / total;
    const dash = Math.max(fraction * circumference, fraction > 0 ? 1 : 0);
    const arc = `<circle cx="70" cy="70" r="${radius}" fill="none" stroke="${CHART_COLORS[index % CHART_COLORS.length]}" stroke-width="22" stroke-dasharray="${dash} ${circumference - dash}" stroke-dashoffset="${-offset}" transform="rotate(-90 70 70)" />`;
    offset += dash;
    return arc;
  });
  return `<div class="donut-wrap"><svg viewBox="0 0 140 140" class="donut-chart">${arcs.join("")}<text x="70" y="66" text-anchor="middle" class="donut-total">${number(total, 2)}</text><text x="70" y="82" text-anchor="middle" class="donut-total-label">total</text></svg><div class="chart-legend donut-legend">${items.map((item, index) => `<span style="--c:${CHART_COLORS[index % CHART_COLORS.length]}">${labelFn(item)} · ${number((valueFn(item) / total) * 100, 1)}%</span>`).join("")}</div></div>`;
}
function columnChart(items, labelFn, valueFn, formatFn = (value) => number(value)) {
  if (!items.length) return `<div class="no-chart">쿼리 결과가 없습니다.</div>`;
  const width = 220, height = 130, padBottom = 18, padTop = 14;
  const max = Math.max(...items.map(valueFn), 0.001);
  const slot = width / items.length;
  const barWidth = Math.max(6, slot * 0.55);
  const bars = items.map((item, index) => {
    const value = valueFn(item);
    const barHeight = Math.max(2, (value / max) * (height - padBottom - padTop));
    const x = index * slot + (slot - barWidth) / 2;
    const y = height - padBottom - barHeight;
    return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}" fill="${CHART_COLORS[index % CHART_COLORS.length]}" rx="2" />`;
  }).join("");
  return `<div class="column-chart-wrap"><svg viewBox="0 0 ${width} ${height}" class="column-chart"><text x="2" y="${padTop}" class="axis-label">${formatFn(max)}</text><line x1="0" y1="${height - padBottom}" x2="${width}" y2="${height - padBottom}" class="axis-line" />${bars}</svg><div class="chart-legend">${items.map((item, index) => `<span style="--c:${CHART_COLORS[index % CHART_COLORS.length]}">${labelFn(item)} · ${formatFn(valueFn(item))}</span>`).join("")}</div></div>`;
}
function resourceTopPanel() {
  const cpu = filteredWorkloadItems(dashboard.topCpuPods, (item) => Number(item.value[1]));
  const memory = filteredWorkloadItems(dashboard.topMemoryPods, (item) => Number(item.value[1]));
  return `<article class="dashboard-panel wide"><header><div><h3>리소스 사용량 Top 5 Pod</h3><p>실제 Prometheus 사용량 상위 Pod입니다. CPU는 millicore(mCPU), 메모리는 working set(MiB)입니다.</p></div>${sourceState("prometheus")}</header>
    <div class="resource-split"><div><h4>CPU (mCPU)</h4>${topBars(cpu, (item) => `${item.metric.namespace}/${item.metric.pod}`, (item) => Number(item.value[1]) * 1000, (value) => number(value, 0))}</div>
    <div><h4>메모리 (MiB)</h4>${topBars(memory, (item) => `${item.metric.namespace}/${item.metric.pod}`, (item) => Number(item.value[1]) / 1024 / 1024, (value) => number(value, 0))}</div></div></article>`;
}
function serverResourceStatusPanel() {
  const nodeInfo = new Map((dashboard.nodeInfo || []).map((item) => [item.metric.instance, item.metric]));
  const nodeNames = new Map((dashboard.nodeInfo || []).map((item) => [item.metric.instance, item.metric.nodename]));
  // 기본 운영 범위 = K8s 노드 + 외부 CI/Harbor. Proxmox 하이퍼바이저는 별도 기반 인프라로 분리한다.
  const operationalInstances = new Set((dashboard.nodeInfo || [])
    .filter((item) => ["prometheus-node-exporter", "vm-node"].includes(item.metric.job))
    .map((item) => item.metric.instance));
  const valueByInstance = (items) => new Map((items || []).map((item) => [item.metric.instance, Number(item.value[1])]));
  const cpu = valueByInstance(dashboard.nodeCpu);
  const memory = valueByInstance(dashboard.nodeMemory);
  const disk = valueByInstance(dashboard.nodeDisk);
  const instances = [...new Set([...nodeNames.keys(), ...cpu.keys(), ...memory.keys(), ...disk.keys()])]
    .filter((instance) => operationalInstances.has(instance))
    .sort((a, b) => text(nodeNames.get(a) || a).localeCompare(text(nodeNames.get(b) || b)));
  const usage = (value) => Number.isFinite(value) ? `<span class="node-usage"><i><em style="width:${Math.max(2, Math.min(100, value))}%"></em></i><b>${number(value, 1)}%</b></span>` : `<span class="node-usage unavailable"><b>미수집</b></span>`;
  const nodeType = (instance) => {
    const job = nodeInfo.get(instance)?.job;
    if (job === "prometheus-node-exporter") return "Kubernetes 노드";
    if (job === "hypervisor") return "Proxmox 호스트";
    if (job === "vm-node") return "외부 CI/CD";
    return "모니터링 호스트";
  };
  return `<article class="dashboard-panel server-resource-panel"><header><div><h3>노드 자원 현황</h3><p>실제 node-exporter 인벤토리입니다. CPU·메모리·디스크는 같은 호스트 행이며, K8s Pod·컨테이너 사용량은 아래 Top 5에서 별도로 봅니다.</p></div>${sourceState("prometheus")}</header>${instances.length ? `<div class="node-resource-table"><div class="node-resource-head"><span>호스트</span><span>구분</span><span>CPU</span><span>메모리</span><span>루트 디스크</span></div>${instances.map((instance) => `<div class="node-resource-row"><strong title="${text(instance)}">${text(nodeNames.get(instance) || instance)}</strong><small>${nodeType(instance)}</small>${usage(cpu.get(instance))}${usage(memory.get(instance))}${usage(disk.get(instance))}</div>`).join("")}</div>` : `<div class="panel-empty">node-exporter 노드 메트릭이 없습니다.</div>`}</article>`;
}
function platformHealthPanel() {
  const rows = dashboard.platformHealth || [];
  if (!rows.length) return `<article class="dashboard-panel side"><header><div><h3>플랫폼 Pod 실행 상태</h3><p>namespace별 Kubernetes Pod phase 기준</p></div>${sourceState("kubernetes")}</header><div class="panel-empty">데이터 없음</div></article>`;
  return `<article class="dashboard-panel side"><header><div><h3>플랫폼 Pod 실행 상태</h3><p>Running은 Pod 실행 상태입니다. Succeeded는 완료된 Job Pod이며, Ready/서비스 정상 여부와는 별도입니다.</p></div>${sourceState("kubernetes")}</header><div class="health-panel platform-pod-panel"><div class="health-row health-head"><span>네임스페이스</span><span>Running</span><span>완료 Job</span><span>대기·실패</span><span>상태</span></div>${rows.map((row) => {
    const total = row.Running + row.Pending + row.Failed + row.Unknown + row.Succeeded;
    const notRunning = Number(row.Pending) + Number(row.Failed) + Number(row.Unknown);
    const healthy = total === 0 || notRunning === 0;
    return `<div class="health-row"><strong>${text(row.namespace)}</strong><span>${row.Running}개</span><span>${row.Succeeded ? `${row.Succeeded}개` : "-"}</span><span class="${notRunning ? "critical-text" : "muted-text"}">${notRunning ? `${notRunning}개` : "없음"}</span><span class="source-state ${healthy ? "ready" : "waiting"}">${healthy ? "확인 없음" : "확인 필요"}</span></div>`;
  }).join("")}</div></article>`;
}
function memoryTimeseriesPanel() {
  const series = filteredWorkloadSeries(dashboard.podMemoryTimeseries, (item) => `${item.metric.namespace}/${item.metric.pod}`, false);
  if (!series.length) return panel("Pod 메모리 사용량 Top 5", "선택 기간 최고값 기준 Pod", "prometheus");
  const scaled = series.map((item) => ({ ...item, values: item.values.map(([t, v]) => [t, Number(v) / 1024 / 1024]) }));
  return `<article class="dashboard-panel"><header><div><h3>Pod 메모리 사용량 Top 5</h3><p>실제 Prometheus · 선택 기간 최고 사용량 기준 · MiB</p></div>${sourceState("prometheus")}</header>${lineChart(scaled, (value) => `${number(value, 0)} MiB`)}</article>`;
}
function p95LatencyPanel() {
  const positiveSamples = (dashboard.serviceP95Timeseries || []).filter((item) => isDashboardService(item.metric?.service)).map((item) => ({
    ...item,
    values: item.values.filter(([, value]) => Number.isFinite(Number(value)) && Number(value) > 0),
  })).filter((item) => item.values.length);
  const series = topSeriesByPeak(positiveSamples, 5);
  const body = series.length ? lineChart(series, (value) => `${number(value, 0)} ms`, { baselineZero: false }) : `<div class="panel-empty">선택 기간에 HTTP latency histogram 관측값이 없습니다.</div>`;
  return `<article class="dashboard-panel"><header><div><h3>p95 Latency Top 5</h3><p>실제 Prometheus · 트래픽이 있던 구간의 최고 지연 기준 서비스</p></div>${sourceState("prometheus")}</header>${body}</article>`;
}
function cpuTimeseriesPanel() {
  const series = filteredWorkloadSeries(dashboard.podCpuTimeseries, (item) => `${item.metric.namespace}/${item.metric.pod}`, false);
  return `<article class="dashboard-panel"><header><div><h3>Pod CPU 사용량 Top 5</h3><p>실제 Prometheus · 선택 기간 최고 사용량 기준 · CPU 사용량은 millicore(mCPU)로 표시</p></div>${sourceState("prometheus")}</header>${lineChart(series, (value) => `${number(Number(value) * 1000, 0)} mCPU`)}</article>`;
}
function containerCpuTimeseriesPanel() {
  const series = filteredWorkloadSeries(dashboard.containerCpuTimeseries, (item) => `${item.metric.namespace}/${item.metric.pod}/${item.metric.container}`);
  const labelled = series.map((item) => ({ ...item, metric: { ...item.metric, service: `${item.metric.namespace}/${item.metric.pod}/${item.metric.container}` } }));
  const body = labelled.length ? lineChart(labelled, (value) => `${number(Number(value) * 1000, 0)} mCPU`) : `<div class="panel-empty">선택한 namespace·Pod·container에 CPU 시계열이 없습니다.</div>`;
  return `<article class="dashboard-panel"><header><div><h3>Container CPU 사용량</h3><p>실제 Prometheus · 기본은 전체 범위 Top 5, 필터 선택 시 해당 workload를 표시</p></div>${sourceState("prometheus")}</header>${body}</article>`;
}
function containerMemoryTimeseriesPanel() {
  const series = filteredWorkloadSeries(dashboard.containerMemoryTimeseries, (item) => `${item.metric.namespace}/${item.metric.pod}/${item.metric.container}`);
  const labelled = series.map((item) => ({ ...item, metric: { ...item.metric, service: `${item.metric.namespace}/${item.metric.pod}/${item.metric.container}` } }));
  const body = labelled.length ? lineChart(labelled.map((item) => ({ ...item, values: item.values.map(([time, value]) => [time, Number(value) / 1024 / 1024]) })), (value) => `${number(value, 0)} MiB`) : `<div class="panel-empty">선택한 namespace·Pod·container에 메모리 시계열이 없습니다.</div>`;
  return `<article class="dashboard-panel"><header><div><h3>Container 메모리 사용량</h3><p>실제 Prometheus working set · 기본은 전체 범위 Top 5</p></div>${sourceState("prometheus")}</header>${body}</article>`;
}
function errorRatePanel() {
  const series = topSeriesByPeak((dashboard.serviceErrorRateTimeseries || []).filter((item) => isDashboardService(item.metric?.destination_service_name)), 5, (item) => item.metric.destination_service_name || "unknown");
  const body = series.length ? lineChart(series, (value) => `${number(value, 2)}%`) : `<div class="panel-empty">선택 기간에 Istio가 관측한 5xx 응답이 없습니다.</div>`;
  return `<article class="dashboard-panel"><header><div><h3>5xx Error Rate Top 5</h3><p>실제 Istio · 선택 기간 최고 오류율 기준 서비스</p></div>${sourceState("prometheus")}</header>${body}</article>`;
}
function podRestartPanel() {
  const restarts = filteredWorkloadItems(dashboard.podRestarts, (item) => Number(item.value[1])).filter((item) => Number(item.value[1]) > 0);
  return `<article class="dashboard-panel"><header><div><h3>Pod 재시작 (최근 1시간)</h3><p>실제 kube_state_metrics 기준</p></div>${sourceState("prometheus")}</header>${restarts.length ? topBars(restarts, (item) => `${item.metric.namespace}/${item.metric.pod}`, (item) => Number(item.value[1]), (value) => `${number(value, 0)}회`) : `<div class="panel-empty">최근 1시간 재시작 없음</div>`}</article>`;
}
function networkIoPanel() {
  const io = filteredWorkloadItems(dashboard.networkIO, (item) => Number(item.value[1]));
  const formatRate = (value) => value >= 1024 * 1024 ? `${number(value / 1024 / 1024, 2)} MiB/s` : value >= 1024 ? `${number(value / 1024, 1)} KiB/s` : `${number(value, 0)} B/s`;
  return `<article class="dashboard-panel"><header><div><h3>Pod 네트워크 송신 Top 5</h3><p>실제 Prometheus · container_network_transmit_bytes_total rate(5m)</p></div>${sourceState("prometheus")}</header>${topBars(io, (item) => `${item.metric.namespace}/${item.metric.pod}`, (item) => Number(item.value[1]), formatRate)}</article>`;
}
function metricSection(title, detail, toneName = "") {
  return `<section class="metric-section-banner ${toneName}"><div><p>METRICS</p><h3>${title}</h3></div><span>${detail}</span></section>`;
}
function nodeSeries(items) {
  const names = new Map((dashboard.nodeInfo || []).map((item) => [item.metric.instance, item.metric.nodename || item.metric.instance]));
  const operationalInstances = new Set((dashboard.nodeInfo || [])
    .filter((item) => ["prometheus-node-exporter", "vm-node"].includes(item.metric.job))
    .map((item) => item.metric.instance));
  return (items || [])
    .filter((item) => operationalInstances.has(item.metric.instance))
    .map((item) => ({ ...item, metric: { host: names.get(item.metric.instance) || item.metric.instance } }));
}
function nodeMetricPanel(title, detail, series, formatValue) {
  return `<article class="dashboard-panel"><header><div><h3>${title}</h3><p>${detail}</p></div>${sourceState("prometheus")}</header>${lineChart(nodeSeries(series), formatValue)}</article>`;
}
function metricsLayout() {
  const trafficPanel = source("prometheus").enabled
    ? `<article class="dashboard-panel"><header><div><h3>서비스 트래픽 Top 5 (RPS)</h3><p>실제 Prometheus · 선택 기간 최고 요청량 기준 서비스</p></div>${sourceState("prometheus")}</header>${lineChart(topSeriesByPeak(selectedSeries(dashboard.serviceRequestRate || []), 5), (value) => `${number(value, 3)} req/s`)}</article>`
    : panel("서비스 트래픽", "RPS를 서비스별 시간축으로 비교", "prometheus");
  const latencyPanel = source("prometheus").enabled ? p95LatencyPanel() : panel("p95 Latency", "전체 요청의 p95 지연시간", "prometheus");
  const errorPanel = source("prometheus").enabled ? errorRatePanel() : panel("5xx Error Rate", "전체 요청 대비 5xx 비율", "prometheus");
  const cpuPanel = source("prometheus").enabled ? cpuTimeseriesPanel() : panel("전체 CPU 사용량", "app 네임스페이스 컨테이너 합계", "prometheus");
  const memoryPanel = source("prometheus").enabled ? memoryTimeseriesPanel() : panel("전체 메모리 사용량", "app 네임스페이스 합계", "prometheus");
  const containerCpuPanel = source("prometheus").enabled ? containerCpuTimeseriesPanel() : panel("Container CPU 사용량", "선택한 container CPU 시계열", "prometheus");
  const containerMemoryPanel = source("prometheus").enabled ? containerMemoryTimeseriesPanel() : panel("Container 메모리 사용량", "선택한 container memory 시계열", "prometheus");
  const resourcePanel = source("prometheus").enabled ? resourceTopPanel() : panel("자원 위험 Top N", "CPU·메모리 상위 Pod와 재시작 횟수", "prometheus", "wide");
  const restartPanel = source("prometheus").enabled ? podRestartPanel() : panel("Pod 재시작", "최근 1시간 재시작 횟수", "prometheus");
  const networkPanel = source("prometheus").enabled ? networkIoPanel() : panel("네트워크 송신 Top N", "Pod별 송신 트래픽", "prometheus");
  const vmPanels = source("prometheus").enabled
    ? `${nodeMetricPanel("VM CPU 사용률", "실제 node-exporter · 호스트별 CPU busy 비율", dashboard.nodeCpuTimeseries, (value) => `${number(value, 1)}%`)}${nodeMetricPanel("VM 메모리 사용률", "실제 node-exporter · 호스트별 MemAvailable 기준", dashboard.nodeMemoryTimeseries, (value) => `${number(value, 1)}%`)}${nodeMetricPanel("VM 루트 디스크 사용률", "실제 node-exporter · 루트 파일시스템 사용 비율", dashboard.nodeDiskTimeseries, (value) => `${number(value, 1)}%`)}${nodeMetricPanel("VM 네트워크 송신", "실제 node-exporter · 가상 인터페이스 제외 · rate(5m)", dashboard.nodeNetworkTimeseries, (value) => value >= 1024 * 1024 ? `${number(value / 1024 / 1024, 2)} MiB/s` : `${number(value / 1024, 1)} KiB/s`)}`
    : panel("VM 인프라", "node-exporter 연결 필요", "prometheus", "wide");
  return `${metricSection("Kubernetes VM · CI/Harbor Infrastructure", "Kubernetes 노드와 CI/Harbor만 표시합니다. Proxmox 하이퍼바이저는 기본 범위에서 제외합니다.", "vm")}
    <section class="panel-grid metrics-layout vm-metrics">${vmPanels}</section>
    ${metricSection("Kubernetes Pod · Container", "전체 namespace의 Pod·container를 조회합니다. 아래에서 범위를 선택할 수 있습니다.", "workload")}
    ${workloadFilterControls()}
    <section class="panel-grid metrics-layout workload-metrics">${cpuPanel}${memoryPanel}${containerCpuPanel}${containerMemoryPanel}${restartPanel}${networkPanel}</section>
    ${metricSection("Application APM Top 5", "서비스 요청량 · 지연시간 · 5xx 오류를 서비스 단위로 비교합니다.", "apm")}
    ${apmServiceFilter()}
    <section class="panel-grid metrics-layout apm-metrics">${trafficPanel}${latencyPanel}${errorPanel}</section>
    ${metricSection("Resource Risk Top 5", "현재 사용량이 높은 Pod를 빠르게 비교합니다. 상위 값만으로 장애를 판정하지 않습니다.", "risk")}
    <section class="panel-grid metrics-layout resource-metrics">${resourcePanel}</section>`;
}
function rawLogRows(streams = dashboard.errorLogs || []) {
  return streams
    .flatMap((stream) => stream.values.map(([ts, line]) => ({
      time: new Date(Number(ts) / 1e6),
      service: stream.stream.service_name || stream.stream.container || "unknown",
      namespace: stream.stream.namespace || "unknown",
      pod: stream.stream.pod || stream.stream.pod_name || "unknown",
      container: stream.stream.container || "unknown",
      traceId: stream.stream.trace_id || stream.stream.traceID || traceIdInLog(line),
      line,
      // `error_severity` 같은 필드명 자체를 오류로 세지 않는다. 구조화 level 또는
      // 예외 키워드가 있어야 실제 오류 수준 로그로 분류한다.
      level: logSeverity(line),
    })))
    .sort((a, b) => b.time - a.time);
}
function traceIdInLog(line) {
  // Alloy/Loki label로 Trace ID가 오지 않아도, JSON/plain-text 원문에 기록된
  // 32-hex ID는 Trace 조사 연결에 사용할 수 있다.
  return String(line || "").match(/\b[0-9a-f]{32}\b/i)?.[0] || "";
}
function logKey(row) { return `${row.time.getTime()}:${row.namespace}:${row.pod}:${row.container}`; }
function traceLogMatches(row, traceId) {
  const normalized = String(traceId || "").toLowerCase();
  return Boolean(normalized) && (String(row.traceId || "").toLowerCase() === normalized || String(row.line || "").toLowerCase().includes(normalized));
}
function logRows({ includeAll = logView === "all" } = {}) {
  const investigationService = dashboard.logInvestigation?.service;
  const filterRows = (sourceRows) => rawLogRows(sourceRows)
    .filter((row) => !investigationService || row.service.includes(investigationService))
    .filter((row) => selectedService() === "all" || row.service.includes(selectedService()))
    .filter((row) => logSelection.namespace === "all" || row.namespace === logSelection.namespace)
    .filter((row) => logSelection.pod === "all" || row.pod === logSelection.pod)
    .filter((row) => logSelection.container === "all" || row.container === logSelection.container)
    .filter((row) => logSelection.level === "all" || row.level === logSelection.level)
    .filter((row) => includeAll || ["error", "warning"].includes(row.level))
    .filter((row) => !logSearchTerm || row.line.toLowerCase().includes(logSearchTerm.toLowerCase()));
  const rows = filterRows(includeAll ? dashboard.errorLogs : dashboard.issueLogs);
  const traceId = dashboard.logInvestigation?.traceId;
  const exact = traceId ? filterRows(dashboard.traceLogs || []).filter((row) => traceLogMatches(row, traceId)) : [];
  // Trace ID가 Loki label/원문에 없으면 서비스+시간 범위 조사 결과를 그대로
  // 남긴다. 빈 결과로 숨기지 않고 정확한 연결이 없었음을 화면에 밝힌다.
  return exact.length ? exact : rows;
}
function structuredLog(line) {
  const value = String(line || "").replace(/^\S+\s+(?:stdout|stderr)\s+[A-Z]\s+/, "").trim();
  const match = value.match(/\{[\s\S]*\}$/);
  if (!match) return null;
  try { return JSON.parse(match[0]); } catch (_) { return null; }
}
function structuredLogLevel(line) {
  const payload = structuredLog(line);
  const direct = payload && (payload.level || payload.severity || payload.log_level);
  const embedded = payload && payload.record && (payload.record.level || payload.record.severity);
  const level = String(direct || embedded || "").toLowerCase();
  return ["fatal", "panic", "error", "warn", "warning", "info", "debug", "trace"].includes(level) ? level : "";
}
function logSeverity(line) {
  const value = String(line || "");
  const structured = structuredLogLevel(value);
  // 구조화 로그의 level은 원문에 error_severity·error_count 같은 필드가 있어도 우선한다.
  // INFO JSON을 오류로 오분류하지 않기 위한 규칙이다.
  if (["fatal", "panic", "error"].includes(structured)) return "error";
  if (["warn", "warning"].includes(structured)) return "warning";
  if (["info", "debug", "trace"].includes(structured)) return "info";
  if (/\b(?:fatal|panic|error|exception|stack trace|traceback)\b/i.test(value) || /\s5\d\d(?:\s|$)/.test(value)) return "error";
  if (/\bwarn(?:ing)?\b/i.test(value)) return "warning";
  return "info";
}
function logFilterPanel() {
  const context = dashboard.logInvestigation;
  const traceRows = context?.traceId ? rawLogRows(dashboard.traceLogs || []).filter((row) => traceLogMatches(row, context.traceId)).length : 0;
  const contextNote = context
    ? `<div class="trace-log-context"><strong>Trace 조사 범위</strong><span>${text(context.service)} · ${date(context.startAt)} ~ ${date(context.endAt)} · Trace ID ${text(context.traceId)}</span><label>실행 LogQL <input readonly value="${escapeHtml(context.query || "조회 준비 중")}" /></label><em>${traceRows ? `Trace ID 원문 일치 로그 ${traceRows}건` : "Trace ID 원문 일치 로그 없음 — 서비스·시간 범위로 표시"}</em><button type="button" data-clear-trace-context>범위 해제</button></div>`
    : "";
  return `<article class="dashboard-panel wide log-filter-panel"><header><div><h3>로그 탐색 필터</h3><p>기본은 ERROR/WARN 조사입니다. Pod·container는 Loki에서 직접 제한하며, 키워드는 원문 메시지에 포함된 문자열을 찾습니다.</p></div>${sourceState("loki")}</header>${contextNote}<div class="log-filter-controls"><div class="log-view-toggle" role="group" aria-label="로그 범위"><button type="button" data-log-view="issues" class="${logView === "issues" ? "active" : ""}">오류 · 경고만</button><button type="button" data-log-view="all" class="${logView === "all" ? "active" : ""}">전체 로그 포함</button></div><label>namespace <select data-log-select="namespace"><option value="all">전체</option></select></label><label>Pod <select data-log-select="pod"><option value="all">전체</option></select></label><label>container <select data-log-select="container"><option value="all">전체</option></select></label><label>수준 <select data-log-select="level"><option value="all">전체</option></select></label><label>원문 메시지 <input data-log-filter type="search" value="${text(logSearchTerm, "")}" placeholder="예: timeout, exception, kafka" /></label></div><span>${logView === "issues" ? "ERROR/WARN만 표시 중 · 전체 INFO 로그는 ‘전체 로그 포함’을 선택하세요." : "전체 로그 표시 중 · Redis 서비스 로그는 Pod에서 mp-redis를 선택하세요."}</span></article>`;
}
function normalizeLogLine(line) {
  const payload = structuredLog(line);
  // JSON 전체나 Kubernetes 메타데이터가 아니라 운영자가 읽을 메시지 필드만 쓴다.
  const candidate = payload && [payload.message, payload.msg, payload.error, payload.exception, payload.reason,
    payload.record && payload.record.message, payload.record && payload.record.msg].find((value) => typeof value === "string" && value.trim());
  const value = String(candidate || line || "")
    .replace(/^\d{4}-\d{2}-\d{2}T[^\s]+\s+(?:stdout|stderr)\s+[A-Z]\s*/i, "")
    .replace(/^\s*(?:ERROR|WARN(?:ING)?|FATAL|PANIC)\s*[:\-]?\s*/i, "")
    .replace(/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/g, "<uuid>")
    .replace(/\b\d+(?:\.\d+)?\b/g, "#")
    .replace(/\s+/g, " ").trim();
  // 파싱하지 못한 JSON 원문은 패턴으로 쓰지 않는다. 원문 로그 표에서만 확인하게 한다.
  return value.startsWith("{") ? "" : value;
}
function issueGroups(keyOf) {
  return [...logRows({ includeAll: false }).reduce((groups, row) => {
    const key = keyOf(row);
    const current = groups.get(key) || { label: key, count: 0, latest: row };
    current.count += 1;
    if (row.time > current.latest.time) current.latest = row;
    groups.set(key, current);
    return groups;
  }, new Map()).values()].sort((a, b) => b.count - a.count || b.latest.time - a.latest.time).slice(0, 5);
}
function issuePatternPanel() {
  const groups = issueGroups((row) => normalizeLogLine(row.line).slice(0, 140)).filter((item) => item.label);
  if (!groups.length) return `<article class="dashboard-panel"><header><div><h3>오류·경고 패턴 Top 5</h3><p>ERROR/WARN 원문의 메시지 필드만 정규화해 반복 유형을 집계합니다. INFO와 JSON 메타데이터는 제외합니다.</p></div>${sourceState("loki")}</header>${empty("오류·경고 패턴 없음", "선택 기간에 사람이 읽을 수 있는 ERROR/WARN 메시지가 없습니다.")}</article>`;
  return `<article class="dashboard-panel"><header><div><h3>오류·경고 패턴 Top 5</h3><p>ERROR/WARN 원문의 메시지 필드만 정규화해 반복 유형을 집계합니다. INFO와 JSON 메타데이터는 제외합니다.</p></div>${sourceState("loki")}</header>${topBars(groups, (item) => item.label, (item) => item.count, (value) => `${value}건`)}</article>`;
}
function issueServicePanel() {
  const groups = issueGroups((row) => row.service === "unknown" ? `${row.namespace} / ${row.container}` : row.service);
  if (!groups.length) return `<article class="dashboard-panel"><header><div><h3>오류·경고 로그 서비스 Top 5</h3><p>ERROR/WARN 로그가 발생한 서비스·컨테이너 순위입니다. 장애 확정이 아니라 조사 우선순위입니다.</p></div>${sourceState("loki")}</header>${empty("오류·경고 서비스 없음", "선택 기간에 ERROR/WARN 로그가 없습니다.")}</article>`;
  return `<article class="dashboard-panel"><header><div><h3>오류·경고 로그 서비스 Top 5</h3><p>ERROR/WARN 로그가 발생한 서비스·컨테이너 순위입니다. 장애 확정이 아니라 조사 우선순위입니다.</p></div>${sourceState("loki")}</header>${topBars(groups, (item) => item.label, (item) => item.count, (value) => `${value}건`)}</article>`;
}
function errorLogTable() {
  const rows = logRows().slice(0, 100);
  if (!rows.length) return empty(logView === "issues" ? "오류·경고 로그 없음" : "표시할 로그 없음", logView === "issues" ? "선택 기간에 ERROR/WARN으로 분류된 Loki 로그가 없습니다. 필요하면 ‘전체 로그 포함’으로 정상 로그를 탐색하세요." : "현재 필터 조건에 맞는 Loki 로그가 없습니다.");
  const title = logView === "issues" ? "최근 오류 · 경고 로그" : "원본 로그";
  return `<section class="table-panel log-stream-panel"><header><div><p>LOKI · LOG EXPLORER</p><h2>${title}</h2><span>현재 필터의 최근 ${rows.length}개입니다. 행을 클릭하면 전체 메시지와 메타데이터를 확인합니다.</span></div>${sourceState("loki")}</header><table><thead><tr><th>시각</th><th>namespace</th><th>Pod / container</th><th>수준</th><th>서비스</th><th>메시지</th><th>Trace ID</th></tr></thead><tbody>${rows.map((row) => `<tr class="log-row ${logKey(row) === selectedLogKey ? "selected" : ""}" data-log-key="${text(logKey(row))}"><td>${row.time.toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}</td><td>${text(row.namespace)}</td><td><strong>${text(row.pod)}</strong><small>${text(row.container)}</small></td><td><span class="log-level ${row.level}">${row.level.toUpperCase()}</span></td><td>${text(row.service)}</td><td class="log-line">${highlightedLogMessage(row.line)}</td><td><code>${row.traceId ? text(row.traceId) : "미기록"}</code></td></tr>`).join("")}</tbody></table></section>`;
}
function logHistogram() {
  const rows = logRows();
  if (!rows.length) return `<div class="no-chart">${logView === "issues" ? "선택 기간에 ERROR/WARN 로그가 없습니다." : "선택 기간에 표시할 로그가 없습니다."}</div>`;
  const buckets = 24;
  const oldest = rows[rows.length - 1].time.getTime();
  const newest = rows[0].time.getTime();
  const span = Math.max(newest - oldest, 60000);
  const counts = Array.from({ length: buckets }, () => ({ total: 0, error: 0, warning: 0, info: 0 }));
  rows.forEach((row) => {
    const index = Math.min(buckets - 1, Math.floor(((row.time.getTime() - oldest) / span) * buckets));
    counts[index].total += 1;
    counts[index][row.level] += 1;
  });
  const max = Math.max(...counts.map((bucket) => bucket.total), 1);
  const midpoint = Math.ceil(max / 2);
  const labels = [0, .5, 1].map((fraction) => chartTime((oldest + span * fraction) / 1000, oldest / 1000, newest / 1000));
  const bucketSeconds = Math.max(1, Math.round(span / buckets / 1000));
  const bucketLabel = bucketSeconds >= 3600 ? `${number(bucketSeconds / 3600, 1)}시간` : bucketSeconds >= 60 ? `${Math.round(bucketSeconds / 60)}분` : `${bucketSeconds}초`;
  return `<div class="log-histogram" data-log-histogram><aside class="log-histogram-y"><span>${max}건</span><span>${midpoint}건</span><span>0건</span><em>로그 건수<br>/ ${bucketLabel} 버킷</em></aside><div class="log-histogram-main"><div class="log-histogram-plot"><div class="log-histogram-grid"></div><div class="log-histogram-bars">${counts.map((bucket, index) => {
    const from = oldest + (span / buckets) * index;
    const to = oldest + (span / buckets) * (index + 1);
    const level = bucket.error ? "critical" : bucket.warning ? "warning" : "info";
    return `<button type="button" class="log-histogram-bar ${level}" style="--bar-height:${(bucket.total / max) * 100}%" data-from="${fullChartTime(from / 1000)}" data-to="${fullChartTime(to / 1000)}" data-total="${bucket.total}" data-error="${bucket.error}" data-warning="${bucket.warning}" data-info="${bucket.info}" aria-label="${fullChartTime(from / 1000)}부터 ${fullChartTime(to / 1000)}까지 로그 ${bucket.total}건"><i></i></button>`;
  }).join("")}</div></div><div class="bar-time-axis"><span>${labels[0]}</span><span>${labels[1]}</span><span>${labels[2]}</span></div></div><div class="log-histogram-tooltip" hidden></div></div>`;
}
function attachLogHistogramTooltips() {
  setupLogFilters();
  document.querySelectorAll("[data-log-histogram]").forEach((histogram) => {
    const tooltip = histogram.querySelector(".log-histogram-tooltip");
    const bars = histogram.querySelectorAll(".log-histogram-bar");
    if (!tooltip || !bars.length) return;
    const hide = () => { tooltip.hidden = true; };
    histogram.addEventListener("mouseleave", hide);
    bars.forEach((bar) => bar.addEventListener("mousemove", (event) => {
      tooltip.innerHTML = `<strong>${bar.dataset.from} ~ ${bar.dataset.to}</strong><span>수집 로그 <b>${bar.dataset.total}건</b></span><span>ERROR/FATAL <b>${bar.dataset.error}건</b></span><span>WARN <b>${bar.dataset.warning}건</b></span><span>INFO/기타 <b>${bar.dataset.info}건</b></span>`;
      const rect = histogram.getBoundingClientRect();
      tooltip.style.left = `${Math.min(Math.max(12, event.clientX - rect.left + 12), Math.max(12, rect.width - 250))}px`;
      tooltip.style.top = `${Math.max(10, event.clientY - rect.top - 86)}px`;
      tooltip.hidden = false;
    }));
  });
}
function closeExpandedPanel() {
  if (!expandedPanel) return;
  const button = expandedPanel.querySelector(".panel-expand");
  if (button) { button.textContent = "⤢"; button.title = "패널 크게 보기"; button.setAttribute("aria-label", "패널 크게 보기"); }
  expandedPanel.classList.remove("panel-expanded");
  expandedPanel = null;
  document.body.classList.remove("panel-expanded-open");
  document.querySelector(".panel-expand-backdrop")?.remove();
}
function setupPanelExpansion() {
  document.querySelectorAll("#dashboardContent .dashboard-panel, #dashboardContent .table-panel, #dashboardContent .hero-panel").forEach((panel) => {
    const header = panel.querySelector(":scope > header");
    if (!header || header.querySelector(".panel-expand")) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "panel-expand";
    button.title = "패널 크게 보기";
    button.setAttribute("aria-label", "패널 크게 보기");
    button.textContent = "⤢";
    button.addEventListener("click", () => {
      if (expandedPanel === panel) { closeExpandedPanel(); return; }
      closeExpandedPanel();
      expandedPanel = panel;
      panel.classList.add("panel-expanded");
      document.body.classList.add("panel-expanded-open");
      const backdrop = document.createElement("div");
      backdrop.className = "panel-expand-backdrop";
      backdrop.addEventListener("click", closeExpandedPanel);
      document.body.append(backdrop);
      button.textContent = "×";
      button.title = "패널 닫기";
      button.setAttribute("aria-label", "패널 닫기");
    });
    header.append(button);
  });
}
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeExpandedPanel(); });
function selectedLogDetailPanel() {
  const rows = logRows();
  const row = rows.find((item) => logKey(item) === selectedLogKey) || rows[0];
  if (!row) return `<aside class="dashboard-panel log-detail-panel"><header><div><h3>선택 로그 상세</h3><p>원본 로그 행을 선택하면 전체 메시지와 메타데이터를 표시합니다.</p></div>${sourceState("loki")}</header><div class="panel-empty">선택할 로그가 없습니다.</div></aside>`;
  const traceAction = row.traceId ? `<button type="button" class="trace-link-button" data-open-trace-id="${text(row.traceId)}">이 Trace 열기</button>` : "";
  return `<aside class="dashboard-panel log-detail-panel"><header><div><h3>선택 로그 상세</h3><p>원본 메시지와 Loki stream label을 그대로 표시합니다.</p></div>${sourceState("loki")}</header><dl><dt>시각</dt><dd>${row.time.toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}</dd><dt>위치</dt><dd>${text(row.namespace)} / ${text(row.pod)} / ${text(row.container)}</dd><dt>수준</dt><dd><span class="log-level ${row.level}">${row.level.toUpperCase()}</span></dd><dt>Trace ID</dt><dd><code>${text(row.traceId)}</code>${traceAction}</dd><dt>원본 메시지</dt><dd class="log-detail-message">${highlightedLogMessage(row.line)}</dd></dl></aside>`;
}
function setupLogFilters() {
  const controls = [...document.querySelectorAll("[data-log-select]")];
  if (!controls.length) return;
  const rows = rawLogRows(logView === "all" ? dashboard.errorLogs : dashboard.issueLogs);
  // Datadog의 Logs Explorer Facet처럼 최근 원문 500행이 아닌 Loki 집계 결과를 쓴다.
  // facet이 조회 실패한 경우에만 원문 결과로 안전하게 폴백한다.
  const facets = dashboard.logFacets?.length ? dashboard.logFacets : rows.map((row) => ({ ...row, count: 0 }));
  const countsBy = (field, values, scopedFacets = facets) => values.map((value) => ({ value, count: scopedFacets.filter((item) => item[field] === value).reduce((sum, item) => sum + Number(item.count || 0), 0) }));
  const namespaces = [...new Set(facets.map((item) => item.namespace))].sort();
  const podFacets = facets.filter((item) => logSelection.namespace === "all" || item.namespace === logSelection.namespace);
  const pods = [...new Set(podFacets.map((item) => item.pod))].sort();
  const containerFacets = podFacets.filter((item) => logSelection.pod === "all" || item.pod === logSelection.pod);
  const containers = [...new Set(containerFacets.map((item) => item.container))].sort();
  const options = { namespace: countsBy("namespace", namespaces), pod: countsBy("pod", pods, podFacets), container: countsBy("container", containers, containerFacets), level: ["error", "warning", "info"].map((value) => ({ value, count: rows.filter((row) => row.level === value).length })) };
  controls.forEach((control) => {
    const key = control.dataset.logSelect;
    const values = options[key] || [];
    if (!values.some((item) => item.value === logSelection[key])) logSelection[key] = "all";
    control.innerHTML = `<option value="all">전체</option>${values.map((item) => `<option value="${text(item.value)}">${text(item.value)}${item.count ? ` (${item.count}건)` : ""}</option>`).join("")}`;
    control.value = logSelection[key];
    control.addEventListener("change", () => { logSelection[key] = control.value; if (key === "namespace") { logSelection.pod = "all"; logSelection.container = "all"; document.querySelector('[data-log-select="pod"]').value = "all"; document.querySelector('[data-log-select="container"]').value = "all"; } if (key === "pod") { logSelection.container = "all"; document.querySelector('[data-log-select="container"]').value = "all"; } refresh(); });
  });
  document.querySelectorAll("[data-log-view]").forEach((button) => button.addEventListener("click", () => { logView = button.dataset.logView; render(); }));
  document.querySelectorAll("[data-log-key]").forEach((row) => row.addEventListener("click", () => { selectedLogKey = row.dataset.logKey; render(); }));
}
function logsLayout() {
  const resultPanel = source("loki").enabled ? errorLogTable() : panel("로그 결과", "시각 · 서비스 · 레벨 · 메시지 · Trace ID", "loki", "wide");
  const histogramPanel = source("loki").enabled
    ? `<article class="dashboard-panel wide"><header><div><h3>${logView === "issues" ? "오류 · 경고 발생량" : "로그 발생량"}</h3><p>실제 Loki · 버킷당 ${logView === "issues" ? "ERROR/WARN" : "원본"} 로그 행 수(건) · 막대에 마우스를 올리면 시간·수준별 건수를 표시합니다.</p></div>${sourceState("loki")}</header>${logHistogram()}</article>`
    : panel("로그 발생량", "시간별 Loki 로그 건수", "loki", "wide");
  const issues = source("loki").enabled ? `<section class="panel-grid log-issue-grid">${issuePatternPanel()}${issueServicePanel()}</section>` : "";
  return `<section class="panel-grid logs-layout">${histogramPanel}${logFilterPanel()}</section>${issues}<section class="logs-explorer-grid">${resultPanel}${selectedLogDetailPanel()}</section>`;
}
function traceRows() {
  // Tempo 검색 응답은 지연시간 순서를 보장하지 않는다. 목록은 최근 정상 요청
  // 덤프가 아니라, 현재 범위·서비스에서 조사할 지연 상위 요청만 보여 준다.
  return (dashboard.recentTraces || [])
    .filter((item) => selectedService() === "all" || traceDisplayService(item) === selectedService() || item.rootServiceName === selectedService())
    .sort((a, b) => Number(b.durationMs || 0) - Number(a.durationMs || 0));
}
function traceDisplayService(item) {
  const endpoint = String(item.rootTraceName || "");
  const match = endpoint.match(/(?:https?:\/\/)?([a-z0-9-]+)\.app\.svc\.cluster\.local/i);
  // Tempo 검색의 root span이 Istio Gateway일 때는, 실제 대상 서비스가 endpoint에 남는다.
  return match?.[1] || item.rootServiceName || "unknown";
}
function traceStartedAt(item) {
  const raw = item.startTimeUnixNano || item.startTime || item.start || item.timestamp;
  if (!raw) return null;
  const numeric = Number(raw);
  return Number.isFinite(numeric) && numeric > 1e14 ? new Date(numeric / 1e6) : new Date(raw);
}
function traceStatus(item) {
  const value = String(item.status || item.statusCode || item.rootServiceStatus || "").toLowerCase();
  return value.includes("error") || value === "2" ? "ERROR" : "OK";
}
function traceTable() {
  const traces = traceRows().slice(0, 30);
  if (!traces.length) return empty("실제 Trace 없음", "선택 기간에 조회된 trace가 없습니다.");
  return `<section class="table-panel trace-table"><header><div><p>TEMPO · TRACE EXPLORER</p><h2>지연 상위 Trace 목록</h2><span>선택 범위의 지연시간 내림차순 Top ${traces.length}입니다. 기준선/SLO 확정 전에는 상위값을 장애로 판정하지 않습니다.</span></div><span>${traces.length} traces</span></header><table><thead><tr><th>시각</th><th>대상 서비스</th><th>Operation / Endpoint</th><th>상태</th><th>총 지연</th><th>Trace ID</th></tr></thead><tbody>${traces.map((item) => `<tr class="trace-row ${item.traceID === selectedTraceId ? "selected" : ""}" data-trace-id="${text(item.traceID)}"><td>${traceStartedAt(item) && !Number.isNaN(traceStartedAt(item).getTime()) ? date(traceStartedAt(item)) : "-"}</td><td><strong>${text(traceDisplayService(item))}</strong></td><td>${text(item.rootTraceName, "/")}</td><td><span class="trace-status ${traceStatus(item) === "ERROR" ? "error" : "ok"}">${traceStatus(item)}</span></td><td>${number(item.durationMs, 0)} ms</td><td><code>${text(item.traceID)}</code></td></tr>`).join("")}</tbody></table></section>`;
}
function traceSummaryPanel() {
  const traces = traceRows();
  if (!traces.length) return panel("느린 요청 Top 5", "실제 서비스·Operation 기준 지연 요청", "tempo", "side");
  const slowest = [...traces].sort((a, b) => b.durationMs - a.durationMs).slice(0, 5);
  const avg = traces.reduce((sum, item) => sum + item.durationMs, 0) / traces.length;
  return `<article class="dashboard-panel side"><header><div><h3>지연 상위 요청 Top 5</h3><p>실제 Tempo · 조회 ${traces.length}건 · 평균 ${number(avg, 0)} ms · 기준선/SLO 판정 전의 상대 순위입니다.</p></div>${sourceState("tempo")}</header>${topBars(slowest, (item) => `${text(traceDisplayService(item))} · ${text(item.rootTraceName, "/")}`, (item) => item.durationMs, (value) => `${number(value, 0)} ms`)}</article>`;
}
function errorTracePanel() {
  const traces = (dashboard.errorTraces || []).filter((item) => selectedService() === "all" || traceDisplayService(item) === selectedService() || item.rootServiceName === selectedService()).slice(0, 10);
  return `<article class="dashboard-panel"><header><div><h3>오류 Trace Top 5</h3><p>Tempo에서 status=error로 기록된 요청입니다. 로그·5xx 전체가 없다는 뜻은 아닙니다.</p></div>${sourceState("tempo")}</header>${traces.length ? `<div class="top-bars">${traces.slice(0, 5).map((item) => `<div class="top-bar-row"><span class="top-bar-label">${text(traceDisplayService(item))} · ${text(item.rootTraceName, "/")}</span><span class="top-bar-value">${number(item.durationMs, 0)} ms</span></div>`).join("")}</div>` : `<div class="panel-empty">선택 기간에 Tempo ERROR span 0건</div>`}</article>`;
}
function latencyDistributionPanel() {
  const traces = traceRows();
  if (!traces.length) return panel("지연 분포", "Trace duration 히스토그램", "tempo");
  const buckets = [50, 100, 250, 500, 1000, 2000, 5000];
  const labels = ["<50ms", "<100ms", "<250ms", "<500ms", "<1s", "<2s", "<5s", "5s+"];
  const counts = new Array(labels.length).fill(0);
  traces.forEach((item) => {
    const index = buckets.findIndex((bound) => item.durationMs < bound);
    counts[index === -1 ? labels.length - 1 : index] += 1;
  });
  const max = Math.max(...counts, 1);
  return `<article class="dashboard-panel"><header><div><h3>지연 분포</h3><p>실제 Tempo · 조회 ${traces.length}건의 duration 분포</p></div>${sourceState("tempo")}</header><div class="top-bars">${labels.map((label, index) => `<div class="top-bar-row"><span class="top-bar-label">${label}</span><div class="top-bar-track"><i style="width:${Math.max(4, (counts[index] / max) * 100)}%"></i></div><span class="top-bar-value">${counts[index]}건</span></div>`).join("")}</div></article>`;
}
function traceSpanAttributes(span) {
  const attributes = [...(span.attributes || []), ...(span.resource?.attributes || [])];
  return Object.fromEntries(attributes.map((attribute) => [attribute.key, Object.values(attribute.value || {})[0]]));
}
function traceResourceSpans(payload) {
  // Tempo has used direct OTLP, { trace: ... }, and wrapper responses across
  // API versions/proxies.  Find the OTLP collection without treating search
  // result summaries as span data.
  const queue = [payload];
  const visited = new Set();
  while (queue.length) {
    const value = queue.shift();
    if (!value || typeof value !== "object" || visited.has(value)) continue;
    visited.add(value);
    if (Array.isArray(value.resourceSpans)) return value.resourceSpans;
    if (Array.isArray(value.batches)) return value.batches;
    ["trace", "data", "result"].forEach((key) => {
      if (value[key] && typeof value[key] === "object") queue.push(value[key]);
    });
  }
  return [];
}
function traceSpans(payload) {
  const resourceSpans = traceResourceSpans(payload);
  return resourceSpans.flatMap((resourceSpan, resourceIndex) => {
    const resource = Object.fromEntries((resourceSpan.resource?.attributes || []).map((attribute) => [attribute.key, Object.values(attribute.value || {})[0]]));
    const scopes = resourceSpan.scopeSpans || resourceSpan.instrumentationLibrarySpans || [];
    return scopes.flatMap((scope, scopeIndex) => (scope.spans || []).map((span, spanIndex) => {
      const attrs = traceSpanAttributes({ ...span, resource: resourceSpan.resource });
      const start = Number(span.startTimeUnixNano || 0) / 1e6;
      const end = Number(span.endTimeUnixNano || 0) / 1e6;
      return {
        id: span.spanId || `${resourceIndex}:${scopeIndex}:${spanIndex}`,
        parentId: span.parentSpanId || "",
        name: span.name || attrs["http.route"] || "unnamed span",
        service: resource["service.name"] || attrs["service.name"] || "unknown",
        start,
        duration: Math.max(0, end - start),
        status: span.status?.code === 2 || String(span.status?.message || "").toLowerCase().includes("error") ? "ERROR" : "OK",
      };
    }));
  }).sort((a, b) => a.start - b.start);
}
function traceTreeRows(spans) {
  const nodes = new Map(spans.map((span) => [span.id, { ...span, children: [] }]));
  const roots = [];
  nodes.forEach((node) => {
    const parent = node.parentId && nodes.get(node.parentId);
    if (parent && parent !== node) parent.children.push(node);
    else roots.push(node);
  });
  const rows = [];
  const visit = (node, depth, ancestry = new Set()) => {
    if (ancestry.has(node.id)) return;
    const nextAncestry = new Set(ancestry);
    nextAncestry.add(node.id);
    node.children.sort((a, b) => a.start - b.start);
    rows.push({ ...node, depth, hasChildren: node.children.length > 0, collapsed: collapsedTraceSpanIds.has(node.id) });
    if (!collapsedTraceSpanIds.has(node.id)) node.children.forEach((child) => visit(child, depth + 1, nextAncestry));
  };
  roots.sort((a, b) => a.start - b.start).forEach((root) => visit(root, 0));
  return rows;
}
function selectedTraceItem() {
  return selectedTraceSummary || (dashboard.recentTraces || []).find((item) => item.traceID === selectedTraceId) || null;
}
function traceInvestigationPanel(spans) {
  const item = selectedTraceItem();
  const service = item ? traceDisplayService(item) : spans[0]?.service || "unknown";
  const startedAt = item ? traceStartedAt(item) : new Date(spans[0].start);
  const total = item?.durationMs || Math.max(...spans.map((span) => span.start + span.duration)) - Math.min(...spans.map((span) => span.start));
  const applicationSpans = spans.filter((span) => !/(?:istio|mp-gw|router outbound|http send)/i.test(`${span.service} ${span.name}`));
  const longest = [...(applicationSpans.length ? applicationSpans : spans)].sort((a, b) => b.duration - a.duration)[0];
  const deploymentCount = startedAt && !Number.isNaN(startedAt.getTime())
    ? (dashboard.deployEvents || []).filter((event) => Math.abs(new Date(event.created_at) - startedAt) <= 5 * 60 * 1000).length
    : 0;
  return `<section class="trace-investigation"><div><small>TRACE INVESTIGATION</small><strong>${text(service)} · ${text(item?.rootTraceName, "request")}</strong><span>총 ${number(total, 1)} ms · 최장 application span ${text(longest.service)} / ${text(longest.name)} ${number(longest.duration, 1)} ms (${number((longest.duration / Math.max(total, 1)) * 100, 0)}%)</span></div><div class="trace-clues"><small>동시간대 운영 단서</small><span>${deploymentCount ? `±5분 ReplicaSet 생성 ${deploymentCount}건` : "±5분 배포 변경 없음"}</span><em>Pod 자원·재시작은 아래 조사 이동으로 확인</em></div><div class="trace-investigation-actions"><button type="button" data-open-trace-logs>관련 로그 조사</button><button type="button" data-open-trace-metrics>Metrics·Pod 조사</button><button type="button" data-open-trace-events>배포·Event 조사</button></div></section>`;
}
function traceWaterfallPanel() {
  const payload = dashboard.selectedTrace;
  const spans = traceSpans(payload);
  if (!selectedTraceId) return `<section class="table-panel trace-waterfall"><header><div><p>TEMPO · TRACE DETAIL</p><h2>선택 Trace 호출 흐름</h2><span>목록에서 Trace 한 건을 선택하면 서비스별 span과 지연 구간을 표시합니다.</span></div>${sourceState("tempo")}</header>${empty("Trace를 선택하세요", "위 Trace 목록의 행을 클릭하세요.")}</section>`;
  if (!spans.length) {
    const responseShape = payload && typeof payload === "object" ? Object.keys(payload).join(", ") || "빈 객체" : "응답 없음";
    const detail = dashboard.selectedTraceError
      ? `Tempo 상세 조회 실패: ${dashboard.selectedTraceError}`
      : `Tempo 응답에 OTLP span 컬렉션이 없습니다. 최상위 키: ${responseShape}`;
    return `<section class="table-panel trace-waterfall"><header><div><p>TEMPO · TRACE DETAIL</p><h2>선택 Trace 호출 흐름</h2><span>Trace ID ${text(selectedTraceId)}</span></div>${sourceState("tempo")}</header>${empty("Span 상세 미수집", detail)}</section>`;
  }
  const first = spans[0].start;
  const total = Math.max(...spans.map((span) => span.start + span.duration)) - first || 1;
  const rows = traceTreeRows(spans);
  return `<section class="table-panel trace-waterfall"><header><div><p>TEMPO · TRACE DETAIL</p><h2>선택 Trace 호출 흐름</h2><span>Trace ID ${text(selectedTraceId)} · ${spans.length} spans · 부모/자식 span은 같은 시간축에서 겹쳐 보입니다.</span></div>${sourceState("tempo")}</header>${traceInvestigationPanel(spans)}<div class="trace-tree-head"><span>Service · Operation</span><span>0 ms</span><span>${number(total / 2, 1)} ms</span><span>${number(total, 1)} ms</span><span>경과 시간</span></div><div class="waterfall-list trace-tree-list">${rows.map((span) => `<div class="waterfall-row trace-tree-row" style="--depth:${span.depth}"><div class="trace-tree-label">${span.hasChildren ? `<button type="button" class="trace-tree-toggle" data-span-toggle="${text(span.id)}" aria-expanded="${!span.collapsed}">${span.collapsed ? "▸" : "▾"}</button>` : `<i class="trace-tree-leaf"></i>`}<div><strong>${text(span.service)}</strong><span>${text(span.name)}</span></div></div><div class="waterfall-track"><i class="${span.status === "ERROR" ? "error" : ""}" style="left:${Math.max(0, ((span.start - first) / total) * 100)}%;width:${Math.max(2, (span.duration / total) * 100)}%"></i></div><b>${number(span.duration, 1)} ms</b><em class="${span.status === "ERROR" ? "error" : ""}">${span.status}</em></div>`).join("")}</div></section>`;
}
function tracesLayout() {
  const listPanel = source("tempo").enabled ? traceTable() : panel("Trace 목록", "서비스 · endpoint · duration · status · trace ID", "tempo", "wide");
  const summaryPanel = source("tempo").enabled ? traceSummaryPanel() : panel("느린 요청 Top 5", "지연이 큰 서비스·Operation", "tempo", "side");
  const errorPanel = source("tempo").enabled ? errorTracePanel() : panel("오류 Trace", "status=error 검색 결과", "tempo");
  const distributionPanel = source("tempo").enabled ? latencyDistributionPanel() : panel("지연 분포", "Trace duration 히스토그램", "tempo");
  return `<section class="panel-grid traces-layout">${summaryPanel}${errorPanel}${distributionPanel}</section>${listPanel}${traceWaterfallPanel()}`;
}
const KNOWN_SERVICES = ["account", "pantry", "recipe", "recipebook", "price", "mealplan", "notify", "chat", "ocr", "operations", "frontend"];
const DATA_LAYER = ["PostgreSQL", "Redis", "Elasticsearch", "Kafka"];
function serviceCatalogRows() {
  const rate = dashboard.serviceRate || [];
  const rateByService = new Map(rate.map((item) => [item.metric.service, Number(item.value[1])]));
  const errorByService = new Map((dashboard.serviceErrorRate || []).map((item) => [item.metric.destination_service_name, Number(item.value[1])]));
  const durationByService = new Map((dashboard.serviceDuration || []).map((item) => [item.metric.service, Number(item.value[1])]));
  // instant query는 화면 갱신 순간 요청이 끊기면 빈 값이 될 수 있다. 같은 기간의 range
  // 마지막 유효 표본을 보완값으로 쓰되, 그래도 없으면 미수집으로 남긴다.
  const durationRangeByService = new Map((dashboard.serviceP95Timeseries || []).map((item) => [item.metric.service, apmLast([item])]));
  const incidentsByService = new Map();
  (dashboard.incidents || []).forEach((incident) => (incident.affected_services || []).forEach((service) => incidentsByService.set(service, (incidentsByService.get(service) || 0) + 1)));
  const anomalyByService = new Map();
  dashboard.anomalies.forEach((item) => {
    const service = serviceIdentity(item.service);
    anomalyByService.set(service, (anomalyByService.get(service) || 0) + 1);
  });
  const names = [...new Set([...KNOWN_SERVICES, ...rate.map((item) => item.metric.service)])].filter(isDashboardService).sort();
  return names.map((name) => {
    const hasMetrics = rateByService.has(name);
    const error = errorByService.get(name) || 0;
    const incidentCount = incidentsByService.get(name) || 0;
    const anomalyCount = anomalyByService.get(name) || 0;
    return {
      name,
      hasMetrics,
      rps: hasMetrics ? rateByService.get(name) : null,
      error,
      p95: durationByService.get(name) ?? (durationRangeByService.get(name) == null ? null : durationRangeByService.get(name) / 1000),
      incidentCount,
      anomalyCount,
      statusTone: incidentCount ? "critical" : anomalyCount || error ? "warning" : hasMetrics ? "normal" : "neutral",
      statusLabel: incidentCount ? "조사중" : error ? "오류 관찰" : anomalyCount ? "탐지됨" : hasMetrics ? "정상" : "계측 미수집",
    };
  });
}
function syncServiceFilter() {
  const filter = $("#serviceFilter");
  if (!filter) return;
  const previous = filter.value || "all";
  const names = serviceCatalogRows().map((row) => row.name);
  filter.innerHTML = `<option value="all">전체 서비스</option>${names.map((name) => `<option value="${text(name)}">${text(name)}</option>`).join("")}`;
  filter.value = names.includes(previous) ? previous : "all";
}
function syncWorkloadFilters() {
  const namespaceFilter = $("#namespaceFilter");
  const podFilter = $("#podFilter");
  const containerFilter = $("#containerFilter");
  if (!namespaceFilter || !podFilter || !containerFilter) return;
  const allSeries = [...(dashboard.podCpuTimeseries || []), ...(dashboard.podMemoryTimeseries || [])];
  const namespaces = [...new Set(allSeries.map((item) => item.metric.namespace).filter(Boolean))].sort();
  const previousNamespace = workloadSelection.namespace || "all";
  namespaceFilter.innerHTML = `<option value="all">전체</option>${namespaces.map((value) => `<option value="${text(value)}">${text(value)}</option>`).join("")}`;
  namespaceFilter.value = namespaces.includes(previousNamespace) ? previousNamespace : "all";
  workloadSelection.namespace = namespaceFilter.value;
  const selectedNs = namespaceFilter.value;
  const pods = [...new Set(allSeries.filter((item) => selectedNs === "all" || item.metric.namespace === selectedNs).map((item) => item.metric.pod).filter(Boolean))].sort();
  const previousPod = workloadSelection.pod || "all";
  podFilter.innerHTML = `<option value="all">전체</option>${pods.map((value) => `<option value="${text(value)}">${text(value)}</option>`).join("")}`;
  podFilter.value = pods.includes(previousPod) ? previousPod : "all";
  workloadSelection.pod = podFilter.value;
  const selectedPodName = podFilter.value;
  const containers = [...new Set([...(dashboard.containerCpuTimeseries || []), ...(dashboard.containerMemoryTimeseries || [])]
    .filter((item) => (selectedNs === "all" || item.metric.namespace === selectedNs) && (selectedPodName === "all" || item.metric.pod === selectedPodName))
    .map((item) => item.metric.container).filter(Boolean))].sort();
  const previousContainer = workloadSelection.container || "all";
  containerFilter.innerHTML = `<option value="all">전체</option>${containers.map((value) => `<option value="${text(value)}">${text(value)}</option>`).join("")}`;
  containerFilter.value = containers.includes(previousContainer) ? previousContainer : "all";
  workloadSelection.container = containerFilter.value;
}
function workloadFilterControls() {
  return `<div class="scoped-filter-row workload-controls" aria-label="Kubernetes workload 범위 선택">
    <span>Workload 범위</span>
    <label>네임스페이스 <select id="namespaceFilter"><option value="all">전체</option></select></label>
    <label>Pod <select id="podFilter"><option value="all">전체</option></select></label>
    <label>컨테이너 <select id="containerFilter"><option value="all">전체</option></select></label>
  </div>`;
}
function apmServiceFilter() {
  const selected = $("#serviceFilter")?.value || "all";
  const names = serviceCatalogRows().map((row) => row.name);
  return `<div class="scoped-filter-row apm-controls" aria-label="APM 서비스 범위 선택"><span>APM 범위</span><label>서비스 <select id="metricsServiceFilter"><option value="all" ${selected === "all" ? "selected" : ""}>전체 서비스</option>${names.map((name) => `<option value="${text(name)}" ${name === selected ? "selected" : ""}>${text(name)}</option>`).join("")}</select></label></div>`;
}
function serviceCatalogPanel() {
  const rows = serviceCatalogRows();
  const traceCounts = new Map();
  (dashboard.recentTraces || []).forEach((item) => {
    const service = traceDisplayService(item);
    traceCounts.set(service, (traceCounts.get(service) || 0) + 1);
  });
  return `<article class="dashboard-panel wide apm-service-table"><header><div><h3>서비스 비교</h3><p>서비스 행을 누르면 Trace·로그·Pod 상세로 이동합니다. p95는 마지막 유효 표본, Trace는 Tempo 조회 표본 수입니다.</p></div>${sourceState("prometheus")}</header><div class="table-wrap"><table><thead><tr><th>서비스</th><th>상태</th><th>현재 RPS</th><th>p95</th><th>5xx</th><th>Trace 표본</th><th>조사 신호</th></tr></thead><tbody>${rows.map((row) => `<tr data-apm-service="${text(row.name)}"><td><strong>${text(row.name)}</strong><small>상세 조사</small></td><td><span class="status ${row.statusTone}">${row.statusLabel}</span></td><td>${row.rps == null ? "-" : `${number(row.rps, 3)} req/s`}</td><td>${row.p95 == null ? "-" : `${number(Number(row.p95) * 1000, 0)} ms`}</td><td class="${row.error ? "critical-text" : ""}">${number(row.error, 3)} req/s</td><td>${number(traceCounts.get(row.name) || 0, 0)}</td><td>${number(row.anomalyCount + row.incidentCount, 0)}건</td></tr>`).join("")}</tbody></table></div></article>`;
}
function servicePerformancePanel() {
  // Atatus의 Endpoints 패널(막대 차트 3개 + 인라인 미니바 표) 참고.
  // 단, 우리 텔레메트리엔 URL 경로(endpoint) 라벨이 없다(Prometheus/Istio 둘 다 카디널리티상 미수집,
  // Tempo rootTraceName도 `<service>/*` 와일드카드뿐) — 앱 계측을 건드리지 않는 한 이보다 세분화 불가.
  // 그래서 실제로 존재하는 가장 세밀한 단위인 "서비스"로 같은 문법을 적용한다.
  const rows = serviceCatalogRows().filter((row) => row.hasMetrics);
  if (!rows.length) return panel("서비스 성능 Top 5", "요청량 · p95 · 오류 상위 서비스", "prometheus", "wide");
  const byRps = [...rows].sort((a, b) => (b.rps || 0) - (a.rps || 0)).slice(0, 5);
  const byP95 = [...rows].sort((a, b) => (Number(b.p95) || 0) - (Number(a.p95) || 0)).slice(0, 5);
  const byError = [...rows].sort((a, b) => (b.error || 0) - (a.error || 0)).slice(0, 5);
  const maxRps = Math.max(...rows.map((row) => row.rps || 0), 0.001);
  const maxP95 = Math.max(...rows.map((row) => (Number(row.p95) || 0) * 1000), 0.001);
  const maxError = Math.max(...rows.map((row) => row.error || 0), 0.001);
  return `<article class="dashboard-panel wide"><header><div><h3>서비스 성능 Top 5</h3><p>실제 Prometheus/Istio 집계 · endpoint 라벨 미수집으로 서비스 단위까지만 세분화</p></div>${sourceState("prometheus")}</header>
    <div class="triple-column-charts">
      <div><h4>Requests (RPS)</h4>${columnChart(byRps, (row) => row.name, (row) => row.rps || 0, (v) => number(v, 2))}</div>
      <div><h4>p95 Latency</h4>${columnChart(byP95, (row) => row.name, (row) => (Number(row.p95) || 0) * 1000, (v) => `${number(v, 0)}ms`)}</div>
      <div><h4>Errors (req/s)</h4>${columnChart(byError, (row) => row.name, (row) => row.error || 0, (v) => number(v, 3))}</div>
    </div>
    <div class="table-wrap"><table class="mini-bar-table"><thead><tr><th>서비스</th><th>Requests</th><th>p95</th><th>Errors</th><th>Error Rate</th></tr></thead><tbody>${rows.map((row) => {
      const errorRate = row.rps ? (row.error / row.rps) * 100 : 0;
      return `<tr><td><strong>${text(row.name)}</strong></td><td>${miniBar(row.rps || 0, maxRps)}</td><td>${miniBar((Number(row.p95) || 0) * 1000, maxP95, 0)}</td><td>${miniBar(row.error || 0, maxError, 3)}</td><td>${miniBar(errorRate, 100, 1, "%")}</td></tr>`;
    }).join("")}</tbody></table></div></article>`;
}
function dataLayerPanel() {
  const dataHealth = (dashboard.platformHealth || []).find((row) => row.namespace === "data");
  const lag = dashboard.kafkaLag || [];
  const topLag = lag.length ? Math.max(...lag.map((item) => Number(item.value[1]))) : null;
  return `<article class="dashboard-panel"><header><div><h3>데이터 계층</h3><p>PostgreSQL · Redis · Elasticsearch · Kafka</p></div>${sourceState("kubernetes")}</header><div class="top-bars">${DATA_LAYER.map((label) => {
    let value = "Pod 상태는 K8s 연결 필요";
    if (dataHealth) {
      const total = dataHealth.Running + dataHealth.Pending + dataHealth.Failed + dataHealth.Unknown + dataHealth.Succeeded;
      value = `data ns ${dataHealth.Running}/${total} Running`;
    }
    if (label === "Kafka" && topLag != null) value = `Consumer Lag 최대 ${number(topLag, 0)}건`;
    return `<div class="top-bar-row"><span class="top-bar-label">${label}</span><span class="top-bar-value">${value}</span></div>`;
  }).join("")}</div></article>`;
}
function selectedServiceHealthPanel() {
  const services = groupedServices();
  if (!services.length) return panel("선택 서비스 건강도", "모니터·Anomaly·Incident 통합 상태", "operations_db", "side");
  const top = services[0];
  const incidentCount = (dashboard.incidents || []).filter((incident) => (incident.affected_services || []).includes(top.service)).length;
  return `<article class="dashboard-panel side"><header><div><h3>선택 서비스 건강도</h3><p>가장 이상징후 많은 서비스 자동 선택</p></div>${sourceState("operations_db")}</header><dl class="snapshot-meta"><div><dt>서비스</dt><dd><strong>${text(top.service)}</strong></dd></div><div><dt>이상징후</dt><dd>${top.total}건 (critical ${top.critical})</dd></div><div><dt>최근 지표</dt><dd>${text(top.latest.metric)} · ${date(top.latest.evaluatedAt)}</dd></div><div><dt>관련 Incident</dt><dd>${incidentCount}건</dd></div></dl></article>`;
}
function deployPanel() {
  const events = (dashboard.deployEvents || []).slice().sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 8);
  if (!events.length) return panel("의존성 · Pod · 배포", "서비스 호출 관계와 최근 운영 변경", "kubernetes");
  return `<article class="dashboard-panel"><header><div><h3>최근 배포 (Pod)</h3><p>실제 Kubernetes ReplicaSet 생성 시각 · 의존성 맵은 Tempo 연동 후 추가</p></div>${sourceState("kubernetes")}</header><div class="top-bars">${events.map((item) => `<div class="top-bar-row"><span class="top-bar-label">${item.namespace}/${item.deployment}</span><span class="top-bar-value">${date(item.created_at)}</span></div>`).join("")}</div></article>`;
}
function httpFailureRatePanel() {
  const series = dashboard.errorRateTimeseries || [];
  const hasTraffic = (dashboard.rpsTimeseries || []).some((item) => item.values?.some(([, value]) => Number(value) > 0));
  const hasSeries = series.length && series.some((item) => item.values?.length);
  const body = !hasTraffic
    ? `<div class="no-chart">선택 기간에 앱 HTTP 요청이 없어 5xx 비율을 계산하지 않습니다.</div>`
    : hasSeries
      ? lineChart(series.map((item) => ({ ...item, metric: { service: "5xx 비율(%)" } })), (value) => `${number(value, 2)}%`)
      : `<div class="no-chart">Istio HTTP 요청 시계열이 없습니다. Istio 메트릭 수집 상태를 확인하세요.</div>`;
  return `<article class="dashboard-panel wide"><header><div><h3>HTTP Failure Rate</h3><p>실제 Istio 메시 기준 · 전체 5xx 비율 시계열입니다. 트래픽이 없으면 0% 그래프 대신 미측정으로 표시합니다.</p></div>${sourceState("prometheus")}</header>${body}</article>`;
}
function responseCodeBreakdownPanel() {
  const codes = (dashboard.responseCodeBreakdown || []).filter((item) => Number(item.value[1]) > 0);
  const sorted = codes.slice().sort((a, b) => Number(b.value[1]) - Number(a.value[1]));
  const chart = sorted.length
    ? donutChart(sorted, (item) => item.metric.response_code, (item) => Number(item.value[1]))
    : `<div class="no-chart">현재 트래픽 0 req/s — 응답 코드 없음</div>`;
  return `<article class="dashboard-panel side"><header><div><h3>HTTP Failure Codes</h3><p>실제 Istio 메시 기준 · 응답 코드 분포(req/s)</p></div>${sourceState("prometheus")}</header>${chart}</article>`;
}
function servicesLayout() {
  if (selectedService() === "all") return apmServiceLanding();
  const service = apmSelectedService();
  if (!service) return empty("APM 서비스 없음", "서비스 메트릭 또는 카탈로그가 수집되면 APM 상세를 표시합니다.");
  const row = serviceCatalogRows().find((item) => item.name === service) || { name: service, statusLabel: "계측 미수집", statusTone: "neutral", rps: null, error: 0, p95: null, anomalyCount: 0, incidentCount: 0 };
  const requestSeries = apmSeries(dashboard.serviceRequestRate, service, "service");
  const p95Series = apmSeries(dashboard.serviceP95Timeseries, service, "service");
  const p50Series = apmSeries(dashboard.serviceP50Timeseries, service, "service");
  const p99Series = apmSeries(dashboard.serviceP99Timeseries, service, "service");
  const errorSeries = apmErrorSeries(service, requestSeries);
  const clientErrorSeries = apmClientErrorSeries(service, requestSeries);
  const p95 = row.p95 == null ? apmLast(p95Series) : Number(row.p95) * 1000;
  return `<section class="apm-service-shell">${apmHeroPanel(row)}<section class="apm-kpi-grid">${apmKpiPanel(row, "Service status", 1, () => row.statusLabel, row.statusTone)}${apmKpiPanel(row, "Request rate", row.rps, (value) => `${number(value, 3)} req/s`)}${apmKpiPanel(row, "5xx error rate", apmLatestErrorRate(service, requestSeries), (value) => `${number(value, 2)}%`)}${apmKpiPanel(row, "p95 latency", p95, (value) => `${number(value, 0)} ms`)}${apmActiveInstancesPanel(row, service)}${apmLatestDeploymentPanel(row, service)}</section><section class="apm-detail-grid">${apmTimeseriesPanel(service, "Request rate", "서비스 전체 RPS · endpoint 라벨은 미수집", requestSeries, (value) => `${number(value, 3)} req/s`)}${apmErrorRatesPanel(service, clientErrorSeries, errorSeries)}${apmLatencyPercentilesPanel(service, p50Series, p95Series, p99Series)}</section><section class="apm-investigation-grid">${apmResourcePanel(service)}${apmDependencyPanel(service)}${apmLogsPanel(service)}${apmTracePanel(service)}${apmRuntimePanel(service)}${apmDeploymentsPanel(service)}</section></section>`;
}
function apmServiceLanding() {
  return `<section class="apm-service-shell"><section class="apm-hero"><div><p>APM · SERVICE INVESTIGATION</p><h2>조사할 서비스를 선택하세요</h2><span>APM은 서비스 하나의 요청·오류·지연·Trace를 조사하는 화면입니다. 전체 비교는 Metrics에서 확인합니다.</span></div></section>${serviceCatalogPanel()}</section>`;
}
function apmActiveInstancesPanel(row, service) {
  const count = (dashboard.topCpuPods || []).filter((item) => String(item.metric?.pod || "").includes(service)).length;
  return apmKpiPanel(row, "Active instances", count || null, (value) => `${number(value, 0)} pods`);
}
function apmLatestDeploymentPanel(row, service) {
  const event = (dashboard.deployEvents || []).filter((item) => String(item.deployment || "").includes(service)).sort((a, b) => new Date(b.created_at) - new Date(a.created_at))[0];
  return apmKpiPanel(row, "Latest deployment", event ? 1 : null, () => event ? date(event.created_at) : "-");
}
function apmAllServicesLayout() {
  const rows = serviceCatalogRows();
  const latencySeries = topSeriesByPeak((dashboard.serviceP95Timeseries || []).filter((item) => isDashboardService(item.metric?.service)).map((item) => ({ ...item, values: (item.values || []).filter(([, value]) => Number.isFinite(Number(value)) && Number(value) >= 0) })), 5);
  const requestSeries = topSeriesByPeak((dashboard.serviceRequestRate || []).filter((item) => isDashboardService(item.metric?.service)), 5);
  const requestMeasured = rows.filter((row) => row.hasMetrics).length;
  const latencyMeasured = rows.filter((row) => row.p95 != null).length;
  const errorSeries = rows.flatMap((row) => apmErrorSeries(row.name));
  const hasErrors = errorSeries.some((item) => item.values?.some(([, value]) => Number(value) > 0));
  const errorTopSeries = topSeriesByPeak(errorSeries, 5);
  return `<section class="apm-service-shell"><section class="apm-hero"><div><p>APM · APPLICATION OVERVIEW</p><h2>전체 서비스 성능</h2><span>APM 공통 흐름인 Calls → Latency → Failures → 느린 Resource → 서비스 상세 순서입니다.</span></div><div><span class="status normal">요청 ${requestMeasured} · p95 ${latencyMeasured} / ${rows.length}</span><small>Tempo 표본 ${(dashboard.recentTraces || []).length} · 활성 Incident ${(dashboard.incidents || []).length}</small></div></section><section class="apm-kpi-grid">${apmKpiPanel({ name: "전체 서비스" }, "현재 Calls/sec", dashboard.overview?.rps, (value) => `${number(value, 3)} req/s`)}${apmKpiPanel({ name: "전체 서비스" }, "전체 p95", dashboard.overview?.p95Ms, (value) => `${number(value, 0)} ms`)}${apmKpiPanel({ name: "전체 서비스" }, "전체 Failure rate", dashboard.overview?.errorRatePercent, (value) => `${number(value, 2)}%`)}${apmKpiPanel({ name: "전체 서비스" }, "계측 범위", requestMeasured, (value) => `요청 ${number(value, 0)}개`, "normal")}</section><section class="apm-application-grid">${apmOverviewTrendPanel("Calls per second", "서비스 Top 5 · 실제 HTTP 요청 rate · 기간 최고값 기준", requestSeries, (value) => `${number(value, 3)} req/s`)}${apmLatencyDistributionPanel()}${apmOverviewTrendPanel("p95 Latency", "서비스 Top 5 · HTTP histogram percentile · 기간 최고값 기준", latencySeries, (value) => `${number(value, 0)} ms`)}${apmSlowResourcePanel()}${apmOverviewTrendPanel("Failure rate", "Istio 5xx · 서비스 Top 5 · 0%도 실제 관측값으로 표시", errorTopSeries, (value) => `${number(value, 2)}%`)}${apmFailureSummaryPanel(hasErrors)}</section>${serviceCatalogPanel()}</section>`;
}
function apmOverviewTrendPanel(title, detail, series, format) {
  const body = series.length ? lineChart(series, format, { baselineZero: false }) : `<div class="panel-empty">선택 기간에 ${text(title)} 시계열이 없습니다.</div>`;
  return `<article class="dashboard-panel apm-overview-trend"><header><div><h3>${text(title)}</h3><p>${text(detail)}</p></div>${sourceState("prometheus")}</header>${body}</article>`;
}
function apmLatencyDistributionPanel() {
  const traces = dashboard.recentTraces || [];
  if (!traces.length) return `<article class="dashboard-panel apm-overview-side"><header><div><h3>Latency distribution</h3><p>Tempo Trace duration 분포</p></div>${sourceState("tempo")}</header><div class="panel-empty">Tempo Trace 표본이 없습니다.</div></article>`;
  const buckets = [50, 100, 250, 500, 1000, 2000, 5000];
  const labels = ["&lt;50ms", "&lt;100ms", "&lt;250ms", "&lt;500ms", "&lt;1s", "&lt;2s", "&lt;5s", "5s+"];
  const counts = new Array(labels.length).fill(0);
  traces.forEach((item) => { const index = buckets.findIndex((bound) => Number(item.durationMs) < bound); counts[index === -1 ? labels.length - 1 : index] += 1; });
  const max = Math.max(...counts, 1);
  return `<article class="dashboard-panel apm-overview-side"><header><div><h3>Latency distribution</h3><p>Tempo · 조회 ${traces.length}개 Trace duration</p></div>${sourceState("tempo")}</header><div class="top-bars">${labels.map((label, index) => `<div class="top-bar-row"><span class="top-bar-label">${label}</span><div class="top-bar-track"><i style="width:${Math.max(4, (counts[index] / max) * 100)}%"></i></div><span class="top-bar-value">${counts[index]}</span></div>`).join("")}</div></article>`;
}
function apmSlowResourcePanel() {
  const groups = new Map();
  (dashboard.recentTraces || []).forEach((item) => {
    const service = traceDisplayService(item); const resource = item.rootTraceName || "resource 미분류"; const key = `${service}|${resource}`;
    const group = groups.get(key) || { service, resource, durations: [] }; group.durations.push(Number(item.durationMs) || 0); groups.set(key, group);
  });
  const rows = [...groups.values()].map((item) => ({ ...item, peak: Math.max(...item.durations), p95: item.durations.slice().sort((a, b) => a - b)[Math.max(0, Math.ceil(item.durations.length * .95) - 1)] })).sort((a, b) => b.p95 - a.p95).slice(0, 5);
  const body = rows.length ? `<div class="apm-investigation-list">${rows.map((row) => `<button type="button" data-apm-service="${text(row.service)}"><span>${text(row.service)} · ${text(row.resource)}</span><b>p95 ${number(row.p95, 0)} ms</b><em>max ${number(row.peak, 0)} ms</em></button>`).join("")}</div>` : `<div class="panel-empty">Tempo resource 표본이 없습니다.</div>`;
  return `<article class="dashboard-panel apm-overview-side"><header><div><h3>Slow resources</h3><p>Tempo root resource · p95 상위 5개</p></div>${sourceState("tempo")}</header>${body}</article>`;
}
function apmFailureSummaryPanel(hasErrors) {
  return `<article class="dashboard-panel apm-overview-side"><header><div><h3>Failure summary</h3><p>Istio 5xx 실패 신호 요약</p></div>${sourceState("prometheus")}</header><div class="apm-error-state ${hasErrors ? "warning" : "normal"}"><strong>${hasErrors ? "5xx 관측됨" : "현재 5xx 없음"}</strong><span>${hasErrors ? "서비스 비교 표에서 실패율이 있는 서비스를 선택해 Trace·Logs를 조사하세요." : "요청이 있는 서비스의 5xx율이 0%입니다."}</span></div></article>`;
}
function apmLatencyRankPanel(series) {
  const rows = series.map((item) => {
    const values = (item.values || []).map(([, value]) => Number(value)).filter(Number.isFinite);
    return { name: item.metric?.service || "unknown", last: values.at(-1), peak: Math.max(...values) };
  }).sort((a, b) => b.peak - a.peak).slice(0, 5);
  const body = rows.length ? `<div class="apm-latency-rank">${rows.map((row) => `<button type="button" data-apm-service="${text(row.name)}"><span>${text(row.name)}</span><i><em style="width:${Math.max(4, (row.peak / Math.max(rows[0].peak, 1)) * 100)}%"></em></i><b>현재 ${number(row.last, 0)} ms</b><strong>최대 ${number(row.peak, 0)} ms</strong></button>`).join("")}</div>` : `<div class="panel-empty">선택 기간에 p95 histogram 표본이 없습니다.</div>`;
  return `<article class="dashboard-panel"><header><div><h3>p95 지연 상위 서비스</h3><p>기간 중 최고 p95 기준 · 행을 누르면 상세 조사</p></div>${sourceState("prometheus")}</header>${body}</article>`;
}
function apmErrorStatusPanel(hasErrors, errorLogCount) {
  const body = hasErrors ? `<div class="apm-error-state warning"><strong>5xx 관측됨</strong><span>서비스 비교 표에서 5xx req/s와 관련 Trace를 확인하세요.</span></div>` : `<div class="apm-error-state normal"><strong>현재 5xx 없음</strong><span>Istio 요청 메트릭에서 5xx 오류율은 0%입니다.</span></div>`;
  return `<article class="dashboard-panel"><header><div><h3>오류 상태 · 로그</h3><p>5xx는 Istio, ERROR/WARN 원문은 Loki 기준</p></div>${sourceState("loki")}</header>${body}<div class="apm-log-summary"><span>ERROR/WARN 로그</span><strong>${number(errorLogCount, 0)}건</strong><button type="button" data-open-view="logs">Logs 열기</button></div></article>`;
}
function apmSelectedService() {
  const selected = selectedService();
  if (selected !== "all") return selected;
  return serviceCatalogRows().find((row) => row.hasMetrics)?.name || serviceCatalogRows()[0]?.name || "";
}
function apmSeries(series, service, label) {
  return (series || []).filter((item) => item.metric?.[label] === service).map((item) => ({ ...item, metric: { ...item.metric, service } }));
}
function apmLast(series) {
  const values = (series || []).flatMap((item) => item.values || []).filter(([, value]) => Number.isFinite(Number(value)));
  return values.length ? Number(values[values.length - 1][1]) : null;
}
function apmErrorSeries(service, requestSeries = apmSeries(dashboard.serviceRequestRate, service, "service")) {
  const observed = apmSeries(dashboard.serviceErrorRateTimeseries, service, "destination_service_name");
  if (observed.length || !requestSeries.some((item) => item.values?.some(([, value]) => Number(value) > 0))) return observed;
  return requestSeries.map((item) => ({ ...item, metric: { service }, values: (item.values || []).map(([timestamp]) => [timestamp, "0"]) }));
}
function apmClientErrorSeries(service, requestSeries = apmSeries(dashboard.serviceRequestRate, service, "service")) {
  const observed = apmSeries(dashboard.service4xxRateTimeseries, service, "destination_service_name");
  if (observed.length || !requestSeries.some((item) => item.values?.some(([, value]) => Number(value) > 0))) return observed;
  return requestSeries.map((item) => ({ ...item, metric: { service }, values: (item.values || []).map(([timestamp]) => [timestamp, "0"]) }));
}
function apmLatestErrorRate(service, requestSeries) {
  const observed = apmLast(apmErrorSeries(service, requestSeries));
  return observed == null ? null : observed;
}
function apmErrorRatesPanel(service, clientSeries, serverSeries) {
  const series = [{ name: "4xx", values: clientSeries }, { name: "5xx", values: serverSeries }].flatMap(({ name, values }) => values.map((item) => ({ ...item, metric: { service: name } })));
  const body = series.length ? lineChart(series, (value) => `${number(value, 2)}%`, { baselineZero: false }) : `<div class="panel-empty">Istio HTTP 오류율 시계열이 없습니다.</div>`;
  return `<article class="dashboard-panel"><header><div><h3>HTTP error rate</h3><p>${text(service)} · 4xx와 5xx를 분리합니다. timeout/exception 라벨은 미수집입니다.</p></div>${sourceState("prometheus")}</header>${body}</article>`;
}
function apmLatencyPercentilesPanel(service, p50, p95, p99) {
  const named = [["p50", p50], ["p95", p95], ["p99", p99]].flatMap(([name, values]) => values.map((item) => ({ ...item, metric: { service: name } })));
  const body = named.length ? lineChart(named, (value) => `${number(value, 0)} ms`, { baselineZero: false }) : `<div class="panel-empty">HTTP latency histogram percentile 시계열이 없습니다.</div>`;
  return `<article class="dashboard-panel wide apm-latency-percentiles"><header><div><h3>Latency percentiles</h3><p>${text(service)} · p50 / p95 / p99 · HTTP histogram 기준</p></div>${sourceState("prometheus")}</header>${body}</article>`;
}
function apmHeroPanel(row) {
  const autoSelected = selectedService() === "all";
  return `<section class="apm-hero"><div><p>APM · SERVICE OVERVIEW</p><h2>${text(row.name)}</h2><span>${autoSelected ? "메트릭이 있는 첫 서비스 자동 선택 · 상단 필터에서 변경 가능" : "선택 서비스 기준 · RED → 리소스 → Trace/Logs 조사"}</span></div><div><span class="status ${row.statusTone}">${text(row.statusLabel)}</span><small>활성 Incident ${number(row.incidentCount, 0)} · anomaly ${number(row.anomalyCount, 0)}</small></div></section>`;
}
function apmKpiPanel(row, label, value, format, toneName = "normal") {
  const missing = value === null || value === undefined || !Number.isFinite(Number(value));
  return `<article class="apm-kpi ${toneName}"><small>${text(label)}</small><strong>${missing ? "미수집" : format(value)}</strong><span>${missing ? "선택 기간에 평가 가능한 시계열 없음" : `${text(row.name)} · 실제 수집값`}</span></article>`;
}
function apmTimeseriesPanel(service, title, detail, series, format, options = {}) {
  const hasSamples = series.some((item) => item.values?.some(([, value]) => Number.isFinite(Number(value))));
  const hasSignal = series.some((item) => item.values?.some(([, value]) => Number(value) > 0));
  const body = hasSamples && (hasSignal || options.renderZero) ? lineChart(series, format, { baselineZero: false }) : `<div class="panel-empty">선택 기간에 ${text(title)} 평가 가능한 트래픽이 없습니다.</div>`;
  return `<article class="dashboard-panel"><header><div><h3>${text(title)}</h3><p>${text(service)} · ${text(detail)}</p></div>${sourceState("prometheus")}</header>${body}</article>`;
}
function apmResourcePanel(service) {
  const traces = (dashboard.recentTraces || []).filter((item) => traceDisplayService(item) === service).sort((a, b) => Number(b.durationMs) - Number(a.durationMs));
  const groups = new Map();
  traces.forEach((item) => {
    const name = item.rootTraceName || "resource 미분류";
    const group = groups.get(name) || { name, count: 0, durations: [] };
    group.count += 1; group.durations.push(Number(item.durationMs) || 0); groups.set(name, group);
  });
  const rows = [...groups.values()].map((item) => ({ ...item, max: Math.max(...item.durations, 0), p95: item.durations.sort((a, b) => a - b)[Math.max(0, Math.ceil(item.durations.length * .95) - 1)] || 0 })).sort((a, b) => b.max - a.max).slice(0, 5);
  const content = rows.length ? `<table><thead><tr><th>Trace resource</th><th>표본</th><th>p95</th><th>최대</th></tr></thead><tbody>${rows.map((item) => `<tr><td>${text(item.name)}</td><td>${item.count}</td><td>${number(item.p95, 0)} ms</td><td>${number(item.max, 0)} ms</td></tr>`).join("")}</tbody></table>` : `<div class="panel-empty">Tempo Trace 표본이 없습니다.</div>`;
  return `<article class="dashboard-panel wide"><header><div><h3>리소스 · Endpoint 후보</h3><p>Tempo Trace 표본 기준입니다. Prometheus endpoint 라벨은 아직 미수집입니다.</p></div>${sourceState("tempo")}</header>${content}</article>`;
}
function apmDependencyPanel(service) {
  return `<article class="dashboard-panel"><header><div><h3>의존성</h3><p>선택 서비스의 downstream 조사 진입점</p></div>${sourceState("tempo")}</header><div class="apm-dependency"><strong>${text(service)}</strong><i>→</i><span>Service graph 미수집</span></div><p class="panel-note">집계된 Tempo service graph가 없어 의존성을 추정하지 않습니다. 실제 호출 경로는 지연 Trace Waterfall에서 확인합니다.</p></article>`;
}
function apmTracePanel(service) {
  const traces = (dashboard.recentTraces || []).filter((item) => traceDisplayService(item) === service).sort((a, b) => Number(b.durationMs) - Number(a.durationMs)).slice(0, 5);
  const body = traces.length ? `<div class="apm-investigation-list">${traces.map((item) => `<button type="button" data-apm-trace-id="${text(item.traceID)}"><span>${text(item.rootTraceName, "request")}</span><b>${number(item.durationMs, 0)} ms</b><em>${traceStatus(item)}</em></button>`).join("")}</div>` : `<div class="panel-empty">선택 기간에 지연 Trace가 없습니다.</div>`;
  return `<article class="dashboard-panel"><header><div><h3>지연 상위 Trace</h3><p>클릭하면 트리 Waterfall과 관련 로그 조사로 이동합니다.</p></div>${sourceState("tempo")}</header>${body}</article>`;
}
function apmLogsPanel(service) {
  const rows = rawLogRows(dashboard.issueLogs || []).filter((row) => row.service.includes(service)).slice(0, 5);
  const body = rows.length ? `<div class="apm-investigation-list">${rows.map((row) => `<button type="button" data-apm-log-service="${text(service)}"><span>${text(normalizeLogLine(row.line), "오류 메시지")}</span><b>${row.level.toUpperCase()}</b><em>${date(row.time)}</em></button>`).join("")}</div>` : `<div class="panel-empty">선택 기간에 ERROR/WARN 로그가 없습니다.</div>`;
  return `<article class="dashboard-panel"><header><div><h3>오류 · 경고 로그</h3><p>${text(service)} · Loki ERROR/WARN 원문</p></div>${sourceState("loki")}</header>${body}</article>`;
}
function apmRuntimePanel(service) {
  const pods = (dashboard.topCpuPods || []).filter((item) => String(item.metric?.pod || "").includes(service)).slice(0, 3);
  const restarts = (dashboard.podRestarts || []).filter((item) => String(item.metric?.pod || "").includes(service)).reduce((sum, item) => sum + Number(item.value?.[1] || 0), 0);
  return `<article class="dashboard-panel"><header><div><h3>Runtime · Pod</h3><p>선택 서비스 Pod의 현재 자원·재시작 단서</p></div>${sourceState("prometheus")}</header>${pods.length ? topBars(pods, (item) => item.metric.pod, (item) => Number(item.value[1]), (value) => `${number(value * 1000, 0)} mCPU`) : `<div class="panel-empty">선택 서비스 Pod CPU 시계열 미수집</div>`}<p class="panel-note">최근 1시간 restart ${number(restarts, 0)}회</p></article>`;
}
function apmDeploymentsPanel(service) {
  const events = (dashboard.deployEvents || []).filter((item) => String(item.deployment || "").includes(service)).sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 4);
  const body = events.length ? `<div class="apm-investigation-list">${events.map((item) => `<div><span>${text(item.namespace)}/${text(item.deployment)}</span><em>${date(item.created_at)}</em></div>`).join("")}</div>` : `<div class="panel-empty">선택 기간에 ${text(service)} ReplicaSet 생성 없음</div>`;
  return `<article class="dashboard-panel"><header><div><h3>변경 이력</h3><p>${text(service)} · Kubernetes ReplicaSet 생성 시각</p></div>${sourceState("kubernetes")}</header>${body}</article>`;
}
function kafkaLagPanel() {
  const lag = dashboard.kafkaLag || [];
  const rows = [...lag].sort((a, b) => Number(b.value?.[1]) - Number(a.value?.[1]));
  const body = rows.length ? `<div class="table-wrap"><table><thead><tr><th>Consumer group</th><th>Topic</th><th>Current lag</th><th>상태</th></tr></thead><tbody>${rows.map((item) => { const value = Number(item.value?.[1]) || 0; return `<tr><td><strong>${text(item.metric?.consumergroup)}</strong></td><td>${text(item.metric?.topic)}</td><td>${number(value, 0)}</td><td><span class="status ${value > 0 ? "warning" : "normal"}">${value > 0 ? "지연 관찰" : "정상"}</span></td></tr>`; }).join("")}</tbody></table></div>` : `<div class="panel-empty">Consumer lag 메트릭이 없습니다.</div>`;
  return `<article class="dashboard-panel"><header><div><h3>Consumer lag</h3><p>group/topic별 현재 backlog</p></div>${sourceState("prometheus")}</header>${body}</article>`;
}
function pipelineFailurePanel() {
  const rows = logRows().filter((row) => /kafka|poll|price|elastic|index|ingest/i.test(`${row.service} ${row.line}`)).slice(0, 8);
  if (!rows.length) return `<article class="dashboard-panel"><header><div><h3>수집·색인 실패 이벤트</h3><p>Poller 오류 · retry · 색인 오류 (실제 Loki)</p></div>${sourceState("loki")}</header><div class="panel-empty">선택 기간에 파이프라인 관련 에러 로그 없음</div></article>`;
  return `<article class="dashboard-panel"><header><div><h3>수집·색인 실패 이벤트</h3><p>실제 Loki · Poller/Kafka/색인 관련 에러</p></div>${sourceState("loki")}</header><div class="top-bars">${rows.map((row) => `<div class="top-bar-row"><span class="top-bar-label">${text(row.service)}</span><span class="top-bar-value">${row.time.toLocaleTimeString("ko-KR")}</span></div>`).join("")}</div></article>`;
}
function pipelineFlowPanel() {
  return `<article class="dashboard-panel wide pipeline-flow"><header><div><h3>가격 데이터 흐름</h3><p>운영 구조: Poller → Kafka → price → Elasticsearch / Redis</p></div>${sourceState("prometheus")}</header><div class="flow-steps"><span>Market Poller</span><i>→</i><span>Kafka</span><i>→</i><span>price service</span><i>→</i><span>PostgreSQL</span><i>→</i><span>Elasticsearch · Redis</span></div><p class="flow-note">실제 처리 지연은 아래 Consumer Lag과 Collector anomaly로 확인합니다.</p></article>`;
}
function freshnessPanel() {
  const latest = dashboard.summary?.latest_evaluated_at;
  return `<article class="dashboard-panel"><header><div><h3>AI 탐지기 최신 평가</h3><p>Operations DB에 저장된 마지막 anomaly 평가 시각</p></div>${sourceState("operations_db")}</header><div class="freshness-value"><strong>${latest ? date(latest) : "-"}</strong><span>${latest ? "실제 Collector 기록" : "기록 대기"}</span></div></article>`;
}
function pipelineLayout() {
  const items = scopedAnomalies().filter((item) => /kafka|poll|lag|ingest|index|freshness|consumer/i.test(`${item.metric} ${item.raw?.subject_key || ""}`));
  const lagPanel = source("prometheus").enabled ? kafkaLagPanel() : panel("Kafka 처리량 · Consumer Lag", "Produce/Consume과 Lag 변화", "prometheus");
  const failurePanel = source("loki").enabled ? pipelineFailurePanel() : panel("수집·색인 실패 이벤트", "Poller 오류 · retry · 색인 오류", "loki");
  const matching = (dashboard.pipelineMatchQuality || []).length ? pipelineMatchQualityPanel() : "";
  return `<section class="pipeline-dashboard">${pipelineStatusStrip(items)}${pipelineFlowPanel()}<section class="pipeline-primary-grid">${pipelineConsumerProcessingPanel()}${pipelineSinkDeliveryPanel()}${lagPanel}${failurePanel}${matching}</section></section>`;
}
function pipelineConsumerProcessingPanel() {
  const topicByComponent = { "retail-refiner": "retail.crawl.raw", "deal-notifier": "retail.deal.raw", "recipe-refiner": "recipe.crawl.raw", "user-event-sink": "events.user.activity", "price-anomaly-notifier": "price.anomaly.detected" };
  const records = (dashboard.pipelineRecords || []).filter((item) => item.metric?.result === "success").map((item) => ({ ...item, metric: { service: `${topicByComponent[item.metric.component] || item.metric.component} · ${item.metric.component} consumed/s` } }));
  const p95 = (dashboard.pipelineProcessing || []).map((item) => ({ ...item, metric: { service: `${item.metric.component} p95` } }));
  const body = records.length ? lineChart(records, (value) => `${number(value, 2)} ops/s`) : `<div class="panel-empty">consumer 성공 처리량 메트릭이 없습니다.</div>`;
  const p95Summary = p95.length ? `<p class="panel-note">p95 처리시간: ${p95.map((item) => `${text(item.metric.service)} ${number(apmLast([item]), 2)} ms`).join(" · ")}</p>` : "";
  return `<article class="dashboard-panel"><header><div><h3>Consumer processing</h3><p>성공 records/s · p95 처리시간은 하단 요약</p></div>${sourceState("prometheus")}</header>${body}${p95Summary}</article>`;
}
function pipelineSinkDeliveryPanel() {
  const series = (dashboard.pipelineSinkWrites || []).filter((item) => item.metric?.result === "success").map((item) => ({ ...item, metric: { service: `${item.metric.component} / ${item.metric.sink} success writes/s` } }));
  return `<article class="dashboard-panel"><header><div><h3>Sink delivery</h3><p>PostgreSQL·Redis 성공 write/s</p></div>${sourceState("prometheus")}</header>${series.length ? lineChart(series, (value) => `${number(value, 2)} ops/s`) : `<div class="panel-empty">sink write 메트릭이 없습니다.</div>`}</article>`;
}
function pipelineMatchQualityPanel() {
  const rows = dashboard.pipelineMatchQuality || [];
  return `<article class="dashboard-panel"><header><div><h3>Item matching quality</h3><p>item_id matched / total · 현재 값</p></div>${sourceState("prometheus")}</header>${rows.length ? `<div class="top-bars">${rows.map((item) => `<div class="top-bar-row"><span class="top-bar-label">${text(item.metric?.component)}</span><div class="top-bar-track"><i style="width:${Math.max(2, Number(item.value?.[1]) || 0)}%"></i></div><span class="top-bar-value">${number(item.value?.[1], 1)}%</span></div>`).join("")}</div>` : `<div class="panel-empty">item matching 메트릭이 없습니다.</div>`}</article>`;
}
function pipelineStatusStrip(items) {
  const lag = dashboard.kafkaLag || [];
  const maxLag = lag.length ? Math.max(...lag.map((item) => Number(item.value?.[1]) || 0)) : null;
  const errors = logRows().filter((row) => /kafka|poll|price|elastic|index|ingest/i.test(`${row.service} ${row.line}`)).length;
  const latest = dashboard.summary?.latest_evaluated_at;
  const stat = (title, value, detail, toneName = "") => `<article class="pipeline-stat ${toneName}"><small>${title}</small><strong>${value}</strong><span>${detail}</span></article>`;
  return `<section class="pipeline-status-strip">${stat("Pipeline freshness", latest ? date(latest) : "미수집", "Collector 마지막 평가")}${stat("Max consumer lag", maxLag == null ? "미수집" : number(maxLag, 0), "Kafka consumer group", maxLag > 0 ? "warning" : "")}${stat("Pipeline errors", `${errors}건`, "Loki ERROR/WARN", errors ? "warning" : "")}${stat("Pipeline anomalies", `${items.length}건`, "선택 기간 Operations DB", items.length ? "warning" : "")}</section>`;
}
function pipelineDeploymentsPanel() {
  const rows = (dashboard.deployEvents || []).filter((item) => /poll|crawl|price|ingest|index|pipeline|kafka/i.test(`${item.namespace}/${item.deployment}`)).slice(0, 5);
  const body = rows.length ? `<div class="apm-investigation-list">${rows.map((item) => `<div><span>${text(item.namespace)}/${text(item.deployment)}</span><em>${date(item.created_at)}</em></div>`).join("")}</div>` : `<div class="panel-empty">선택 기간에 파이프라인 배포 변경 없음</div>`;
  return `<article class="dashboard-panel"><header><div><h3>최근 변경</h3><p>Kubernetes ReplicaSet 생성 · 처리량/lag 변화와 대조</p></div>${sourceState("kubernetes")}</header>${body}</article>`;
}
function pipelineDataAvailabilityPanel() {
  return `<article class="dashboard-panel pipeline-availability"><header><div><h3>파이프라인 데이터 범위</h3><p>현재 실제 수집 신호와 다음 계측 우선순위</p></div>${sourceState("prometheus")}</header><div><strong>현재</strong><span>Consumer lag · Collector freshness · Loki 실패 로그 · pipeline anomaly · 배포 변경</span></div><div><strong>미수집</strong><span>topic produce/consume throughput · DLQ 건수 · sink write latency · end-to-end event age</span></div></article>`;
}
function snapshotSummary(snapshot) { if (!snapshot) return `<div class="detail-empty">저장된 Evidence Snapshot이 없습니다.</div>`; const packageData = snapshot.package || {}; const keys = Object.keys(packageData).filter((key) => !["metadata", "incident"].includes(key)); return `<dl class="snapshot-meta"><div><dt>Snapshot ID</dt><dd>${text(snapshot.snapshot_id)}</dd></div><div><dt>저장 시각</dt><dd>${date(snapshot.captured_at)}</dd></div><div><dt>근거 항목</dt><dd>${keys.length ? keys.join(" · ") : "Evidence JSON 저장됨"}</dd></div></dl>`; }
function rcaInvestigationCard(incident, snapshot) {
  const state = dashboard.rcaByIncident?.[incident.incident_id];
  const action = `<button type="button" class="rca-start" data-start-rca="${escapeHtml(incident.incident_id)}" ${state?.kind === "loading" ? "disabled" : ""}>${state?.kind === "loading" ? "AI 조사 중..." : "AI 조사 시작"}</button>`;
  if (state?.kind === "result") {
    const result = state.result;
    const causes = (result.causes || []).map((cause) => `<li><strong>${escapeHtml(cause.summary)}</strong><span>${text(cause.confidence, "- ")} · ${cause.evidence?.length || 0}개 근거</span></li>`).join("");
    const checks = (result.checks || []).map((check) => `<li>${escapeHtml(check.action)}</li>`).join("");
    return `<section class="detail-card rca-card"><header><div><p>AI INVESTIGATION</p><h2>Mock RCA 초안</h2><span class="source-state ready">${escapeHtml(result.provider || "mock")} · DRAFT</span></div>${action}</header><p class="detail-text">Evidence Snapshot의 사실을 정리한 조사 초안입니다. 실제 원인 판정이나 자동 조치는 하지 않습니다.</p><div class="rca-result"><section><h3>원인 후보</h3><ul>${causes || "<li>원인 후보가 반환되지 않았습니다.</li>"}</ul></section><section><h3>우선 점검</h3><ol>${checks || "<li>추가 점검 항목이 없습니다.</li>"}</ol></section></div><p class="rca-limitations">${(result.limitations || []).map(escapeHtml).join(" · ")}</p></section>`;
  }
  if (state?.kind === "snapshot_missing") return `<section class="detail-card rca-card"><header><div><p>AI INVESTIGATION</p><h2>RCA 조사</h2><span class="source-state waiting">Evidence Snapshot 없음</span></div>${action}</header><p class="detail-text">RCA API가 404를 반환했습니다. 먼저 Evidence Snapshot을 생성한 뒤 다시 조사하세요.</p></section>`;
  if (state?.kind === "api_error") return `<section class="detail-card rca-card"><header><div><p>AI INVESTIGATION</p><h2>RCA 조사</h2><span class="source-state waiting">API 오류 ${state.status || ""}</span></div>${action}</header><p class="detail-text">${escapeHtml(state.message || "RCA API를 호출하지 못했습니다.")}</p></section>`;
  const snapshotMessage = snapshot ? "Evidence Snapshot이 준비되었습니다. mock RCA를 생성해 조사 초안을 확인할 수 있습니다." : "Evidence Snapshot이 아직 없습니다. 버튼을 누르면 RCA API의 404 상태를 확인할 수 있습니다.";
  return `<section class="detail-card rca-card"><header><div><p>AI INVESTIGATION</p><h2>RCA 조사</h2><span class="source-state ${snapshot ? "ready" : "waiting"}">${snapshot ? "Evidence 준비됨" : "Evidence 없음"}</span></div>${action}</header><p class="detail-text">${snapshotMessage}</p></section>`;
}
function incidentsLayout() { const items = dashboard.incidents || []; if (!items.length) return empty("활성 Incident 없음", "현재 선택 기간에 Operations DB에 저장된 Incident가 없습니다."); const selected = items.find((item) => item.incident_id === selectedIncidentId) || items[0]; selectedIncidentId = selected.incident_id; const snapshot = dashboard.snapshots?.[selected.incident_id]; return `<section class="incident-workbench"><aside class="incident-master"><header><p>INCIDENTS</p><h2>실제 Incident 목록</h2></header>${items.map((item) => `<button class="incident-row ${item.incident_id === selected.incident_id ? "selected" : ""}" data-incident="${item.incident_id}"><span class="status ${tone(item.status)}">${text(item.status)}</span><strong>${text(item.title, "제목 없는 Incident")}</strong><small>${(item.affected_services || []).join(" · ") || "영향 서비스 미분류"}</small><em>${date(item.first_seen_at)}</em></button>`).join("")}</aside><div class="incident-detail"><section class="detail-card"><header><p>INVESTIGATION TIMELINE</p><h2>${text(selected.title, "제목 없는 Incident")}</h2><span>실제 Incident 시각과 관련 Alert 정보를 표시합니다.</span></header><ol class="incident-times"><li><time>${date(selected.first_seen_at)}</time><strong>최초 감지</strong><span>${text(selected.suspected_origin_service, "원인 서비스 미분류")}</span></li><li><time>${date(selected.last_seen_at)}</time><strong>최근 관측</strong><span>관련 Alert ${number(selected.alert_count, 0)}개</span></li></ol></section><section class="detail-card"><header><p>EVIDENCE PACKAGE</p><h2>실제 Evidence Snapshot</h2><span>저장된 조사 근거를 조회합니다.</span></header>${snapshotSummary(snapshot)}</section>${rcaInvestigationCard(selected, snapshot)}</div><aside class="incident-side"><section class="detail-card"><header><p>IMPACT</p><h2>영향 범위</h2></header><p class="detail-text">${(selected.affected_services || []).join(" · ") || "영향 서비스가 아직 분류되지 않았습니다."}</p></section></aside></section>`; }
function detectionPipelinePanel() {
  return `<article class="dashboard-panel side"><header><div><h3>탐지 파이프라인</h3><p>실제 Analyzer 설정값(config.py/models.py)</p></div>${sourceState("operations_db")}</header><dl class="snapshot-meta">
    <div><dt>알고리즘</dt><dd>Rolling Z-score + MAD + 변화율 + 연속구간</dd></div>
    <div><dt>평가 주기</dt><dd>60초 (lookback 120분)</dd></div>
    <div><dt>학습창(baseline)</dt><dd>60 샘플 (최소 30)</dd></div>
    <div><dt>임계값</dt><dd>Z&gt;3.0 · MAD&gt;3.5 · 변화율&gt;50%</dd></div>
    <div><dt>확정 조건</dt><dd>3회 연속 이탈</dd></div>
  </dl></article>`;
}
function anomalyEvidencePanel() {
  const item = selectedAnomaly();
  if (!item) return "";
  const service = serviceIdentity(item.service);
  const detectedAt = new Date(item.evaluatedAt);
  const withinWindow = (value, minutes = 15) => {
    const at = new Date(value);
    return !Number.isNaN(at.getTime()) && !Number.isNaN(detectedAt.getTime()) && Math.abs(at - detectedAt) <= minutes * 60 * 1000;
  };
  const logs = rawLogRows(dashboard.issueLogs || []).filter((row) => row.service.includes(service) && withinWindow(row.time)).slice(0, 3);
  const traces = (dashboard.recentTraces || []).filter((row) => traceDisplayService(row) === service && withinWindow(traceStartedAt(row))).sort((a, b) => Number(b.durationMs) - Number(a.durationMs)).slice(0, 3);
  const deployments = (dashboard.deployEvents || []).filter((row) => String(row.deployment || "").includes(service) && withinWindow(row.created_at, 30)).slice(0, 3);
  const incidents = (dashboard.incidents || []).filter((row) => (row.affected_services || []).some((name) => String(name).includes(service)) && (withinWindow(row.first_seen_at, 30) || withinWindow(row.last_seen_at, 30))).slice(0, 2);
  const snapshot = incidents.map((incident) => dashboard.snapshots?.[incident.incident_id]).find(Boolean);
  const evidence = (title, rows, renderRow, none) => `<section><h4>${title}</h4>${rows.length ? `<ul>${rows.map(renderRow).join("")}</ul>` : `<p>${none}</p>`}</section>`;
  const relative = baselineDelta(item);
  return `<article class="dashboard-panel wide anomaly-evidence-panel"><header><div><p>RCA EVIDENCE</p><h3>선택 anomaly 조사 근거</h3><span>원인 확정 또는 AI 추측이 아닙니다. ${text(item.service)} · ${text(item.metric)} 주변의 실제 관측값만 연결합니다.</span></div><span class="source-state ${snapshot ? "ready" : "waiting"}">${snapshot ? "Evidence 준비됨" : "RCA 미연동"}</span></header>${anomalyRcaFlow(item, logs, traces, deployments, incidents)}${bedrockRcaDemoPanel()}<div class="anomaly-kpis"><div><small>실제값</small><strong>${anomalyValue(item.current, item.metric)}</strong></div><div><small>정상 기준선</small><strong>${anomalyValue(item.baseline, item.metric)}</strong></div><div><small>기준선 대비</small><strong>${relative == null ? "-" : `${relative >= 0 ? "+" : ""}${number(relative * 100, 1)}%`}</strong></div><div><small>점수 상태</small><strong>${anomalyScoreQuality(item) ? "분산 과소" : `Z ${number(item.zScore, 2)}`}</strong></div></div><div class="anomaly-evidence-grid">${evidence("관련 오류·경고 로그", logs, (row) => `<li><time>${date(row.time)}</time><span>${escapeHtml(normalizeLogLine(row.line))}</span></li>`, "탐지 시각 ±15분에 같은 서비스 ERROR/WARN 로그 없음")}${evidence("관련 지연·오류 Trace", traces, (row) => `<li><time>${date(traceStartedAt(row))}</time><span>${number(row.durationMs, 0)} ms · ${escapeHtml(row.rootTraceName || "/")}</span></li>`, "탐지 시각 ±15분에 같은 서비스 Trace 표본 없음")}${evidence("주변 배포 변경", deployments, (row) => `<li><time>${date(row.created_at)}</time><span>${escapeHtml(`${row.namespace}/${row.deployment}`)}</span></li>`, "탐지 시각 ±30분에 해당 서비스 배포 변경 없음")}${evidence("연결 Incident", incidents, (row) => `<li><time>${date(row.first_seen_at)}</time><span>${escapeHtml(row.title || row.incident_id)}</span><button type="button" data-anomaly-incident="${escapeHtml(row.incident_id)}">Incident 열기</button></li>`, "이 anomaly와 시간·서비스가 겹치는 Incident 없음")}</div><footer>${anomalyScoreQuality(item) ? "이 항목은 기준선 분산이 매우 작아 Z-score가 과대할 수 있습니다. 기준선 대비와 실제 로그·Trace를 먼저 확인하세요. " : ""}${snapshot ? "연결 Incident의 Evidence Snapshot이 저장되어 있습니다. Incident 화면에서 근거 패키지를 확인하세요." : "Bedrock RCA는 아직 호출하지 않았습니다. Incident가 생성되고 Evidence Snapshot이 저장된 경우에만 RCA 입력 근거가 준비됩니다."}</footer></article>`;
}
function serviceSeverityPanel() {
  const services = groupedServices().slice(0, 8);
  if (!services.length) return `<article class="dashboard-panel side"><header><div><h3>영향 서비스 · 심각도</h3><p>서비스·심각도·지표별 필터와 우선순위</p></div>${sourceState("operations_db")}</header><div class="panel-empty">선택 기간에 anomaly 없음</div></article>`;
  return `<article class="dashboard-panel side"><header><div><h3>영향 서비스 · 심각도</h3><p>서비스·심각도·지표별 필터와 우선순위</p></div>${sourceState("operations_db")}</header><div class="top-bars">${services.map((item) => `<div class="top-bar-row"><span class="top-bar-label ${item.critical ? "critical-text" : ""}">${text(item.service)}</span><div class="top-bar-track"><i style="width:${Math.max(4, (item.total / services[0].total) * 100)}%"></i></div><span class="top-bar-value">${item.total}건${item.critical ? ` · critical ${item.critical}` : ""}</span></div>`).join("")}</div></article>`;
}
function anomalyRcaFlow(item, logs, traces, deployments, incidents) {
  const deployment = deployments[0];
  const cause = deployment
    ? { state: "근거 있음", title: `배포 변경 · ${deployment.namespace}/${deployment.deployment}`, detail: `${date(deployment.created_at)} · 탐지 시각 ±30분` }
    : { state: "후보 없음", title: "확인된 상태 변경 없음", detail: "현재 수집된 배포·변경 이력에서 시간상 선행 근거가 없습니다." };
  const failure = traces[0]
    ? { state: "관측됨", title: `지연/오류 Trace ${traces[0].durationMs ? `${number(traces[0].durationMs, 0)} ms` : ""}`, detail: traces[0].rootTraceName || "Trace operation 미분류" }
    : logs[0]
      ? { state: "관측됨", title: "오류·경고 로그", detail: normalizeLogLine(logs[0].line) }
      : { state: "미확인", title: "Critical Failure 미확인", detail: "같은 시간 범위의 오류 Trace·ERROR/WARN 로그가 없습니다." };
  const impact = incidents[0]
    ? { state: "연결됨", title: `${(incidents[0].affected_services || []).length}개 영향 서비스`, detail: (incidents[0].affected_services || []).join(" · ") || incidents[0].title }
    : { state: "미확인", title: "영향 범위 미확인", detail: "RUM은 미연동이며, 시간·서비스가 겹치는 Incident도 없습니다." };
  const card = (kind, icon, data, cls) => `<section class="watchdog-card ${cls}"><p>${icon} ${kind}</p><h4>${text(data.title)}</h4><span>${text(data.detail)}</span><em>${data.state}</em></section>`;
  return `<section class="watchdog-rca"><header><div><span class="watchdog-state">ONGOING</span><small>${date(item.evaluatedAt)}부터 · 선택 anomaly</small></div><button type="button" data-open-view="incidents">Incident 보기</button></header><div class="watchdog-flow">${card("ROOT CAUSE", "◎", cause, "root")}<i>→</i>${card("CRITICAL FAILURE", "△", failure, "failure")}<i>→</i>${card("IMPACT", "✦", impact, "impact")}</div><section class="watchdog-detail"><div><p>ROOT CAUSE · 근거 기반 후보</p><h3>${text(cause.title)}</h3><span>${text(cause.detail)}</span></div><div class="watchdog-timeline"><span>탐지 시각</span><i></i><b>${date(item.evaluatedAt)}</b></div></section></section>`;
}
function bedrockRcaDemoPanel() {
  return `<section class="bedrock-rca-demo"><header><div><p>BEDROCK RCA · DEMO OUTPUT</p><h3>RCA 출력 예시</h3><span>아래 내용은 Bedrock 연동 후의 화면 예시이며, 현재 선택 anomaly의 실제 판단이 아닙니다.</span></div><span>DEMO</span></header><div class="bedrock-demo-grid"><section><h4>원인 후보 1</h4><strong>최근 배포 뒤 특정 Pod의 메모리 사용량이 지속 상승</strong><p>예시 근거: 배포 시각이 이상 시작보다 앞서고, 같은 Pod의 메모리 기준선 이탈이 연속 관측됨.</p></section><section><h4>영향/증상</h4><strong>p95 지연 및 오류 로그 증가 여부 확인 필요</strong><p>예시 근거: 같은 시간 범위의 APM 지연·5xx·오류 Trace·Loki 패턴을 함께 평가.</p></section><section><h4>권장 점검 순서</h4><ol><li>배포 버전·ReplicaSet 변경 확인</li><li>메모리 증가와 OOM/재시작 여부 확인</li><li>오류 Trace·로그를 endpoint 기준으로 대조</li></ol></section></div><footer>실제 Bedrock 연동 시에는 Evidence Snapshot의 Metric·Log·Trace·Kubernetes Event·Deployment만 입력으로 사용하고, 각 후보에 근거 링크를 함께 표시합니다.</footer></section>`;
}
function groupedAnomalyEvents() {
  const groups = new Map();
  scopedAnomalies().forEach((item) => {
    const parsed = new Date(item.evaluatedAt);
    if (Number.isNaN(parsed.getTime())) return;
    const key = Math.floor(parsed.getTime() / 60000);
    const group = groups.get(key) || { time: parsed.toISOString(), total: 0, services: new Set(), metrics: new Set(), critical: 0, warning: 0 };
    group.total += 1;
    group.services.add(item.service);
    group.metrics.add(item.metric);
    if (tone(item.status) === "critical") group.critical += 1;
    else if (tone(item.status) === "warning") group.warning += 1;
    groups.set(key, group);
  });
  return [...groups.values()].sort((a, b) => new Date(b.time) - new Date(a.time));
}
function selectedPeriodStart() {
  const hours = Number($("#periodFilter")?.value || 1);
  return new Date(Date.now() - hours * 60 * 60 * 1000);
}
function recentDeploymentEvents() {
  const from = selectedPeriodStart();
  return (dashboard.deployEvents || []).filter((item) => {
    const created = new Date(item.created_at);
    return !Number.isNaN(created.getTime()) && created >= from;
  }).sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
}
function eventSummaryPanel(deploys, workloadEvents, incidents) {
  const cards = [
    ["선택 기간 배포 변경", `${deploys.length}건`, "ReplicaSet 생성 시각 기준", "normal"],
    ["현재 비정상 Workload", `${workloadEvents.length}건`, "Pending · Failed · Unknown", workloadEvents.length ? "warning" : "normal"],
    ["활성 Incident", `${incidents.length}건`, "Operations DB", incidents.length ? "critical" : "normal"],
  ];
  return `<section class="event-summary">${cards.map(([label, value, detail, status]) => `<article><small>${label}</small><strong class="${status}">${value}</strong><span>${detail}</span></article>`).join("")}</section>`;
}
function events() {
  const deploymentRecords = recentDeploymentEvents();
  const deploys = deploymentRecords.map((item) => ({ time: item.created_at, kind: "Deployment", status: "normal", title: `${item.namespace}/${item.deployment}`, detail: "ReplicaSet 생성 또는 rollout 변경" }));
  const workloads = (dashboard.kubernetesWorkloadEvents || []).map((item) => ({
    time: item.created_at,
    status: item.phase === "Failed" ? "critical" : "warning",
    title: `${item.namespace}/${item.name} · ${item.phase}`,
    detail: item.reason || "reason unavailable",
  })).sort((a, b) => new Date(b.time) - new Date(a.time));
  const incidents = dashboard.incidents || [];
  const incidentEvents = incidents.map((item) => ({ time: item.first_seen_at, kind: "Incident", status: tone(item.status), title: text(item.title, "제목 없는 Incident"), detail: (item.affected_services || []).join(" · ") || "영향 서비스 미분류", action: "incidents" }));
  const timeline = [...deploys, ...incidentEvents].sort((a, b) => new Date(b.time) - new Date(a.time)).slice(0, 30);
  const deploymentPanel = `<article class="dashboard-panel"><header><div><h3>최근 배포 변경</h3><p>선택 기간에 생성된 Kubernetes ReplicaSet입니다. 기존에 계속 실행 중인 ReplicaSet은 이벤트로 세지 않습니다.</p></div>${sourceState("kubernetes")}</header>${deploymentRecords.length ? `<div class="event-detail-list">${deploymentRecords.slice(0, 8).map((item) => `<div><time>${date(item.created_at)}</time><strong>${text(item.namespace)}/${text(item.deployment)}</strong><span>ReplicaSet 생성 · 배포 변경 후보</span></div>`).join("")}</div>` : `<div class="panel-empty">선택 기간에 새 배포 변경 없음</div>`}</article>`;
  const workloadPanel = `<article class="dashboard-panel"><header><div><h3>현재 비정상 Kubernetes Workload</h3><p>Pending · Failed · Unknown 상태의 실제 Pod입니다. Completed Job은 정상 이력이므로 제외합니다.</p></div>${sourceState("kubernetes")}</header>${workloads.length ? `<div class="event-detail-list">${workloads.slice(0, 8).map((item) => `<div><time>${date(item.time)}</time><strong>${text(item.title)}</strong><span>${text(item.detail)}</span></div>`).join("")}</div>` : `<div class="panel-empty">현재 비정상 Workload 없음</div>`}</article>`;
  return `${eventSummaryPanel(deploymentRecords, workloads, incidents)}<section class="event-timeline-panel"><header><div><p>OPERATIONS TIMELINE</p><h2>운영 변경 · Incident 이력</h2><span>배포 변경과 Incident만 시간순으로 표시합니다. AI 탐지 원시 레코드는 Anomalies 탭에서 조사합니다.</span></div></header>${timeline.length ? `<ol>${timeline.map((item) => `<li><i class="${tone(item.status)}"></i><time>${date(item.time)}</time><div><strong>${item.kind}</strong><b>${text(item.title)}</b><span>${text(item.detail)}</span></div>${item.action ? `<button data-open-view="${item.action}">Incident 상세</button>` : ""}</li>`).join("")}</ol>` : `<p class="no-data">선택 기간에 배포 변경 또는 Incident 이력이 없습니다.</p>`}</section><section class="event-detail-grid">${workloadPanel}${deploymentPanel}</section>`;
}
function renderView() { if (activeView === "overview") return overview(); if (activeView === "metrics") return metricsLayout(); if (activeView === "events") return events(); if (activeView === "logs") return logsLayout(); if (activeView === "traces") return tracesLayout(); if (activeView === "services") return servicesLayout(); if (activeView === "pipeline") return pipelineLayout(); if (activeView === "anomalies") return `${anomalyPriorityPanel()}<section class="panel-grid anomaly-layout">${anomalyTrendPanel()}${detectionPipelinePanel()}</section>${anomalyEvidencePanel()}${serviceSeverityPanel()}`; if (activeView === "incidents") return incidentsLayout(); return `<section class="panel-grid slo-layout">${panel("SLO 현황", "가용성 · p95 · 데이터 최신성 목표", "prometheus")}${panel("Error Budget", "소진율과 최근 위반 이력", "prometheus")}${panel("SLO 위반 이벤트", "목표 위반과 관련 Incident", "operations_db", "wide")}</section>`; }
function render() { const view = views[activeView]; $("#eyebrow").textContent = view[0]; $("#pageTitle").textContent = view[1]; $("#pageIntro").innerHTML = activeView === "overview" ? (loadError ? `<strong class="load-error">${loadError}</strong>` : "") : `<div><h2>${view[1]}</h2><p>${view[2]}</p></div>${loadError ? `<strong class="load-error">${loadError}</strong>` : ""}`; document.querySelectorAll(".service-filter").forEach((item) => { item.hidden = ["metrics", "pipeline", "events", "incidents", "reliability"].includes(activeView); });
    document.querySelectorAll(".period-filter").forEach((item) => { item.hidden = activeView === "reliability"; }); renderOverviewBanner(); summaryCards(); $("#dashboardContent").innerHTML = renderView(); if (activeView === "metrics") { syncWorkloadFilters(); $("#metricsServiceFilter")?.addEventListener("change", (event) => { $("#serviceFilter").value = event.target.value; render(); }); ["namespaceFilter", "podFilter", "containerFilter"].forEach((id) => { $(`#${id}`)?.addEventListener("change", (event) => { workloadSelection[id.replace("Filter", "").replace("namespace", "namespace").replace("container", "container").replace("pod", "pod")] = event.target.value; syncWorkloadFilters(); render(); }); }); } attachSharedChartTooltips(); attachLogHistogramTooltips(); setupPanelExpansion(); document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === activeView)); document.querySelectorAll("[data-incident]").forEach((button) => button.addEventListener("click", () => { selectedIncidentId = button.dataset.incident; render(); })); document.querySelectorAll("[data-open-view]").forEach((button) => button.addEventListener("click", () => { activeView = button.dataset.openView; render(); })); document.querySelectorAll("[data-log-filter]").forEach((input) => input.addEventListener("change", () => { logSearchTerm = input.value; refresh(); })); }
async function refresh() { try { loadError = ""; await window.loadOperationsLiveData(dashboard); syncServiceFilter(); syncWorkloadFilters(); } catch (error) { dashboard.source = "unavailable"; loadError = "실제 Operations 데이터를 불러오지 못했습니다. Proxy와 DB 연결을 확인하세요."; console.error(error); } render(); }
document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => { activeView = button.dataset.view; render(); }));
document.addEventListener("click", (event) => {
  const rca = event.target.closest("[data-start-rca]");
  if (rca) { startRcaInvestigation(rca.dataset.startRca); return; }
  const anomaly = event.target.closest("[data-anomaly-id]");
  if (anomaly) { selectedAnomalyId = anomaly.dataset.anomalyId; render(); return; }
  const incident = event.target.closest("[data-anomaly-incident]");
  if (incident) { selectedIncidentId = incident.dataset.anomalyIncident; activeView = "incidents"; render(); }
});
async function startRcaInvestigation(incidentId) {
  dashboard.rcaByIncident = dashboard.rcaByIncident || {};
  dashboard.rcaByIncident[incidentId] = { kind: "loading" };
  render();
  try {
    const response = await fetch(operationsApiEndpoint(`/internal/incidents/${encodeURIComponent(incidentId)}/rca`), { method: "POST", headers: { Accept: "application/json" } });
    const payload = await response.json().catch(() => ({}));
    if (response.ok) dashboard.rcaByIncident[incidentId] = { kind: "result", result: payload };
    else if (response.status === 404) dashboard.rcaByIncident[incidentId] = { kind: "snapshot_missing" };
    else dashboard.rcaByIncident[incidentId] = { kind: "api_error", status: response.status, message: payload.detail || "RCA API 요청에 실패했습니다." };
  } catch (error) {
    dashboard.rcaByIncident[incidentId] = { kind: "api_error", message: "RCA API에 연결하지 못했습니다. Proxy와 Operations API 설정을 확인하세요." };
    console.error(error);
  }
  render();
}
async function selectTrace(traceId, summary = null) {
  selectedTraceId = traceId;
  selectedTraceSummary = summary || (dashboard.recentTraces || []).find((item) => item.traceID === traceId) || null;
  collapsedTraceSpanIds = new Set();
  dashboard.selectedTrace = null;
  dashboard.selectedTraceError = "";
  render();
  try {
    await window.loadOperationsTraceDetail(dashboard, selectedTraceId);
  } catch (error) {
    console.warn("Tempo trace detail unavailable", error);
  }
  render();
}
async function openTraceLogs() {
  const item = selectedTraceItem();
  if (!item) return;
  const at = traceStartedAt(item);
  if (!at || Number.isNaN(at.getTime())) return;
  const service = traceDisplayService(item);
  dashboard.logInvestigation = {
    traceId: selectedTraceId,
    service,
    startAt: new Date(at.getTime() - 2 * 60 * 1000).toISOString(),
    endAt: new Date(at.getTime() + 2 * 60 * 1000).toISOString(),
  };
  const serviceFilter = $("#serviceFilter");
  if (serviceFilter && [...serviceFilter.options].some((option) => option.value === service)) serviceFilter.value = service;
  logView = "issues";
  logSearchTerm = "";
  selectedLogKey = "";
  activeView = "logs";
  await refresh();
}
document.addEventListener("click", async (event) => {
  const spanToggle = event.target.closest("[data-span-toggle]");
  if (spanToggle) {
    const spanId = spanToggle.dataset.spanToggle;
    if (collapsedTraceSpanIds.has(spanId)) collapsedTraceSpanIds.delete(spanId);
    else collapsedTraceSpanIds.add(spanId);
    render();
    return;
  }
  const apmService = event.target.closest("[data-apm-service]");
  if (apmService) {
    const service = apmService.dataset.apmService;
    const serviceFilter = $("#serviceFilter");
    if (serviceFilter && [...serviceFilter.options].some((option) => option.value === service)) serviceFilter.value = service;
    activeView = "services";
    render();
    return;
  }
  const apmTrace = event.target.closest("[data-apm-trace-id]");
  if (apmTrace) {
    const traceId = apmTrace.dataset.apmTraceId;
    const summary = (dashboard.recentTraces || []).find((item) => item.traceID === traceId) || null;
    activeView = "traces";
    await selectTrace(traceId, summary);
    return;
  }
  const apmLogs = event.target.closest("[data-apm-log-service]");
  if (apmLogs) {
    const service = apmLogs.dataset.apmLogService;
    const serviceFilter = $("#serviceFilter");
    if (serviceFilter && [...serviceFilter.options].some((option) => option.value === service)) serviceFilter.value = service;
    activeView = "logs";
    render();
    return;
  }
  const openLogs = event.target.closest("[data-open-trace-logs]");
  if (openLogs) { await openTraceLogs(); return; }
  const openMetrics = event.target.closest("[data-open-trace-metrics]");
  if (openMetrics) { activeView = "metrics"; render(); return; }
  const openEvents = event.target.closest("[data-open-trace-events]");
  if (openEvents) { activeView = "events"; render(); return; }
  const clearTraceContext = event.target.closest("[data-clear-trace-context]");
  if (clearTraceContext) { dashboard.logInvestigation = null; await refresh(); return; }
  const traceFromLog = event.target.closest("[data-open-trace-id]");
  if (traceFromLog) { activeView = "traces"; await selectTrace(traceFromLog.dataset.openTraceId); return; }
  const row = event.target.closest("[data-trace-id]");
  if (!row) return;
  const summary = (dashboard.recentTraces || []).find((item) => item.traceID === row.dataset.traceId) || null;
  await selectTrace(row.dataset.traceId, summary);
});
$("#refreshButton").addEventListener("click", refresh); $("#periodFilter").addEventListener("change", refresh); $("#serviceFilter").addEventListener("change", render);
render(); refresh();
