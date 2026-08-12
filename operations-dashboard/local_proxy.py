"""Local Operations Dashboard server.

It serves the static dashboard, exposes read-only dashboard GET endpoints, and
forwards only the allow-listed Incident RCA POST to Operations. Queries are
executed with the local ``psql`` client against the external Operations
database; the browser never receives database credentials.

Set OPERATIONS_DASHBOARD_DATABASE_URL, or the prefixed PG connection variables,
in the shell before starting this server.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlencode, urlparse


DATABASE_URL_ENV = "OPERATIONS_DASHBOARD_DATABASE_URL"
OPERATIONS_API_URL_ENV = "OPERATIONS_DASHBOARD_OPERATIONS_API_URL"
PG_ENV_PREFIX = "OPERATIONS_DASHBOARD_"
MAX_LIMIT = 500

# The dashboard never assumes cluster-local addresses from a developer laptop.
# A source becomes available only when the local/server environment explicitly
# supplies its read-only URL.
OBSERVABILITY_SOURCE_ENVS = {
    "prometheus": "OPERATIONS_DASHBOARD_PROMETHEUS_URL",
    "loki": "OPERATIONS_DASHBOARD_LOKI_URL",
    "tempo": "OPERATIONS_DASHBOARD_TEMPO_URL",
    "kubernetes": "OPERATIONS_DASHBOARD_KUBERNETES_URL",
}


def parse_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("start_at and end_at must be ISO-8601 timestamps") from error
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def query_database(sql: str, variables: dict[str, str]) -> object:
    database_url = os.environ.get(DATABASE_URL_ENV)
    environment = os.environ.copy()
    if database_url:
        command = ["psql", database_url]
    else:
        names = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
        missing = [name for name in names if not environment.get(f"{PG_ENV_PREFIX}{name}")]
        if missing:
            raise RuntimeError(
                f"set {DATABASE_URL_ENV} or "
                + ", ".join(f"{PG_ENV_PREFIX}{name}" for name in missing)
            )
        for name in names:
            environment[name] = environment[f"{PG_ENV_PREFIX}{name}"]
        command = ["psql"]
    command.extend(["-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"])
    for name, value in variables.items():
        command.extend(["-v", f"{name}={value}"])
    # psql only interpolates :'var' when the SQL is read from stdin/-f, not from -c.
    result = subprocess.run(
        command,
        input=sql,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
    )
    return json.loads(result.stdout)


ANOMALIES_SQL = """
select coalesce(json_agg(row_to_json(item)), '[]'::json)
from (
  select metric_id, subject_type, subject_key, labels, evaluated_at, status,
         current_value, baseline, z_score, mad_score, change_rate,
         breached_checks, consecutive_breaches, required_consecutive_windows,
         event_count
  from operations.anomalies
  where evaluated_at between :'start_at'::timestamptz and :'end_at'::timestamptz
  order by evaluated_at desc, metric_id, subject_key
  limit :'limit'::integer
) item;
"""

INCIDENTS_SQL = """
select coalesce(json_agg(row_to_json(item)), '[]'::json)
from (
  select incident_id, status, title, first_seen_at, last_seen_at,
         earliest_alert_id, earliest_alert_name, suspected_origin_service,
         affected_services, alert_count, grouping_reasons, alerts
  from operations.incidents
  where first_seen_at <= :'end_at'::timestamptz
    and last_seen_at >= :'start_at'::timestamptz
  order by last_seen_at desc, incident_id
  limit :'limit'::integer
) item;
"""

SNAPSHOT_SQL = """
select coalesce(json_build_object(
  'snapshot_id', snapshot_id,
  'incident_id', incident_id,
  'captured_at', captured_at,
  'package', evidence_package
), '{}'::json)
from operations.incident_evidence_snapshots
where incident_id = :'incident_id'
order by captured_at desc, snapshot_id desc
limit 1;
"""

SUMMARY_SQL = """
select json_build_object(
  'anomaly_count', (select count(*) from operations.anomalies
                    where evaluated_at between :'start_at'::timestamptz and :'end_at'::timestamptz),
  'incident_count', (select count(*) from operations.incidents
                     where first_seen_at <= :'end_at'::timestamptz
                       and last_seen_at >= :'start_at'::timestamptz),
  'latest_evaluated_at', (select max(evaluated_at) from operations.anomalies
                          where evaluated_at between :'start_at'::timestamptz and :'end_at'::timestamptz)
);
"""


def query_prometheus_range(promql: str, start_at: str, end_at: str, step: str) -> object:
    prometheus_url = os.environ.get(OBSERVABILITY_SOURCE_ENVS["prometheus"])
    if not prometheus_url:
        raise RuntimeError("set OPERATIONS_DASHBOARD_PROMETHEUS_URL first")
    query = urlencode(
        {
            "query": promql,
            "start": start_at,
            "end": end_at,
            "step": step,
        }
    )
    with urllib.request.urlopen(
        f"{prometheus_url}/api/v1/query_range?{query}", timeout=10
    ) as response:
        payload = json.loads(response.read())
    if payload.get("status") != "success":
        raise urllib.error.URLError(payload.get("error", "prometheus query failed"))
    return payload["data"]["result"]


def query_prometheus_instant(promql: str) -> object:
    prometheus_url = os.environ.get(OBSERVABILITY_SOURCE_ENVS["prometheus"])
    if not prometheus_url:
        raise RuntimeError("set OPERATIONS_DASHBOARD_PROMETHEUS_URL first")
    query = urlencode({"query": promql})
    with urllib.request.urlopen(
        f"{prometheus_url}/api/v1/query?{query}", timeout=10
    ) as response:
        payload = json.loads(response.read())
    if payload.get("status") != "success":
        raise urllib.error.URLError(payload.get("error", "prometheus query failed"))
    return payload["data"]["result"]


def query_loki_range(logql: str, start_at: str, end_at: str, limit: str) -> object:
    loki_url = os.environ.get(OBSERVABILITY_SOURCE_ENVS["loki"])
    if not loki_url:
        raise RuntimeError("set OPERATIONS_DASHBOARD_LOKI_URL first")
    query = urlencode(
        {
            "query": logql,
            "start": start_at,
            "end": end_at,
            "limit": limit,
            "direction": "backward",
        }
    )
    with urllib.request.urlopen(
        f"{loki_url}/loki/api/v1/query_range?{query}", timeout=10
    ) as response:
        payload = json.loads(response.read())
    if payload.get("status") != "success":
        raise urllib.error.URLError(payload.get("error", "loki query failed"))
    return payload["data"]["result"]


def query_loki_facets(start_at: str, end_at: str) -> list[dict[str, object]]:
    """Return log-bearing Kubernetes labels and counts for the selected window.

    This is an aggregate Loki query, not a Kubernetes Pod inventory. A value is
    included only when that Pod/container actually emitted indexed logs in the
    selected period, matching the behavior of a Logs Explorer facet.
    """
    loki_url = os.environ.get(OBSERVABILITY_SOURCE_ENVS["loki"])
    if not loki_url:
        raise RuntimeError("set OPERATIONS_DASHBOARD_LOKI_URL first")
    start = datetime.fromisoformat(start_at)
    end = datetime.fromisoformat(end_at)
    window_seconds = max(1, int((end - start).total_seconds()))
    logql = (
        'sum by (namespace, pod, container) '
        f'(count_over_time({{namespace=~"app|data|pipeline"}}[{window_seconds}s]))'
    )
    query = urlencode({"query": logql, "time": end_at})
    with urllib.request.urlopen(
        f"{loki_url}/loki/api/v1/query?{query}", timeout=10
    ) as response:
        payload = json.loads(response.read())
    if payload.get("status") != "success":
        raise urllib.error.URLError(payload.get("error", "loki facet query failed"))
    facets: list[dict[str, object]] = []
    for item in payload.get("data", {}).get("result", []):
        metric = item.get("metric", {})
        value = item.get("value", [None, "0"])
        try:
            count = int(float(value[1]))
        except (IndexError, TypeError, ValueError):
            count = 0
        if not metric.get("namespace") or not metric.get("pod"):
            continue
        facets.append({
            "namespace": metric["namespace"],
            "pod": metric["pod"],
            "container": metric.get("container", "unknown"),
            "count": count,
        })
    return sorted(facets, key=lambda item: (-int(item["count"]), str(item["pod"])))


def query_tempo_search(traceql: str, start_at: str, end_at: str, limit: str) -> object:
    tempo_url = os.environ.get(OBSERVABILITY_SOURCE_ENVS["tempo"])
    if not tempo_url:
        raise RuntimeError("set OPERATIONS_DASHBOARD_TEMPO_URL first")
    query = urlencode({"q": traceql, "start": start_at, "end": end_at, "limit": limit})
    with urllib.request.urlopen(
        f"{tempo_url}/api/search?{query}", timeout=10
    ) as response:
        payload = json.loads(response.read())
    traces = payload.get("traces", [])
    return [item for item in traces if isinstance(item.get("durationMs"), (int, float))]


def query_tempo_trace(trace_id: str) -> object:
    """Read one Tempo trace for the local dashboard waterfall; never mutates Tempo."""
    tempo_url = os.environ.get(OBSERVABILITY_SOURCE_ENVS["tempo"])
    if not tempo_url:
        raise RuntimeError("set OPERATIONS_DASHBOARD_TEMPO_URL first")
    if not trace_id or len(trace_id) > 128:
        raise ValueError("valid trace_id is required")
    escaped_trace_id = quote(trace_id, safe="")
    # Tempo v2 returns the documented OTLP JSON trace shape.  Keep the v1
    # endpoint as a compatibility fallback for an older in-cluster Tempo.
    try:
        with urllib.request.urlopen(
            f"{tempo_url}/api/v2/traces/{escaped_trace_id}", timeout=10
        ) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        if error.code != HTTPStatus.NOT_FOUND:
            raise
    with urllib.request.urlopen(
        f"{tempo_url}/api/traces/{escaped_trace_id}", timeout=10
    ) as response:
        return json.loads(response.read())


def query_kubernetes(path: str) -> object:
    kubernetes_url = os.environ.get(OBSERVABILITY_SOURCE_ENVS["kubernetes"])
    if not kubernetes_url:
        raise RuntimeError("set OPERATIONS_DASHBOARD_KUBERNETES_URL first")
    with urllib.request.urlopen(f"{kubernetes_url}{path}", timeout=10) as response:
        return json.loads(response.read())


def pod_phase_summary(namespace: str) -> object:
    payload = query_kubernetes(f"/api/v1/namespaces/{namespace}/pods")
    counts = {"Running": 0, "Pending": 0, "Failed": 0, "Unknown": 0, "Succeeded": 0}
    for item in payload.get("items", []):
        phase = item.get("status", {}).get("phase", "Unknown")
        counts[phase] = counts.get(phase, 0) + 1
    return {"namespace": namespace, **counts}


def workload_events(namespace: str) -> list[object]:
    """Return only abnormal workload states for the dashboard event stream.

    This is intentionally read-only and excludes Completed/Succeeded Job history,
    which is normal for CronJobs and does not represent an active failure.
    """
    payload = query_kubernetes(f"/api/v1/namespaces/{namespace}/pods")
    events = []
    for item in payload.get("items", []):
        status = item.get("status", {})
        phase = status.get("phase", "Unknown")
        if phase not in {"Pending", "Failed", "Unknown"}:
            continue
        container_states = status.get("containerStatuses", [])
        reason = status.get("reason", "")
        for container in container_states:
            state = container.get("state", {})
            reason = reason or state.get("waiting", {}).get("reason", "") or state.get("terminated", {}).get("reason", "")
        owner = next(
            (reference.get("name") for reference in item.get("metadata", {}).get("ownerReferences", []) if reference.get("name")),
            "",
        )
        events.append({
            "namespace": namespace,
            "name": item.get("metadata", {}).get("name", "unknown"),
            "owner": owner,
            "phase": phase,
            "reason": reason or "reason unavailable",
            "created_at": item.get("metadata", {}).get("creationTimestamp", ""),
        })
    return events


def deploy_events(namespace: str) -> object:
    payload = query_kubernetes(f"/apis/apps/v1/namespaces/{namespace}/replicasets")
    events = []
    for item in payload.get("items", []):
        replicas = item.get("status", {}).get("replicas", 0)
        if not replicas:
            continue
        owner = next(
            (o["name"] for o in item["metadata"].get("ownerReferences", []) if o["kind"] == "Deployment"),
            item["metadata"]["name"],
        )
        events.append({
            "namespace": namespace,
            "deployment": owner,
            "created_at": item["metadata"]["creationTimestamp"],
        })
    return events


_HEALTH_PATHS = {
    "prometheus": "/-/healthy",
    "loki": "/ready",
    "tempo": "/status",
    "kubernetes": "/version",
}


def _probe(url: str, path: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}{path}", timeout=2) as response:
            return response.status < 400
    except Exception:
        return False


def source_status() -> dict[str, dict[str, object]]:
    """Probe each source live; a set env var alone does not mean it is reachable."""
    status: dict[str, dict[str, object]] = {
        "operations_db": {"enabled": True, "label": "읽기 전용 PostgreSQL"}
    }
    for name, environment_name in OBSERVABILITY_SOURCE_ENVS.items():
        url = os.environ.get(environment_name)
        if not url:
            status[name] = {"enabled": False, "label": "읽기 URL 미설정"}
            continue
        reachable = _probe(url, _HEALTH_PATHS[name])
        status[name] = {
            "enabled": reachable,
            "label": "연결됨(응답 확인)" if reachable else "URL 설정됐지만 응답 없음",
        }
    return status


class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            return super().do_GET()
        try:
            payload = self.api_payload(parsed.path, parse_qs(parsed.query))
        except ValueError as error:
            self.send_error(HTTPStatus.BAD_REQUEST, str(error))
            return
        except subprocess.CalledProcessError:
            self.send_error(HTTPStatus.BAD_GATEWAY, "Operations database query failed")
            return
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(error))
            return
        except urllib.error.URLError as error:
            self.send_error(HTTPStatus.BAD_GATEWAY, f"Prometheus query failed: {error}")
            return
        body = json.dumps(payload, ensure_ascii=False, default=str).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        prefix = "/api/internal/incidents/"
        suffix = "/rca"
        if not parsed.path.startswith(prefix) or not parsed.path.endswith(suffix):
            self.send_error(HTTPStatus.NOT_FOUND, "dashboard API path is not allowed")
            return

        incident_id = parsed.path[len(prefix) : -len(suffix)]
        if not incident_id or "/" in incident_id:
            self.send_error(HTTPStatus.BAD_REQUEST, "invalid incident id")
            return
        try:
            status_code, body = forward_incident_rca(incident_id)
        except RuntimeError as error:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(error))
            return
        except urllib.error.URLError as error:
            self.send_error(HTTPStatus.BAD_GATEWAY, f"Operations API request failed: {error}")
            return

        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def api_payload(path: str, params: dict[str, list[str]]) -> object:
        if path == "/api/internal/anomalies":
            return query_database(ANOMALIES_SQL, query_window(params))
        if path == "/api/internal/incidents":
            return query_database(INCIDENTS_SQL, query_window(params))
        if path == "/api/dashboard/summary":
            return query_database(SUMMARY_SQL, query_window(params))
        if path == "/api/dashboard/sources":
            return source_status()
        if path == "/api/prometheus/query_range":
            window = query_window(params)
            step = params.get("step", ["60"])[0]
            promql = params.get("promql", [None])[0]
            if not promql:
                raise ValueError("promql is required")
            return query_prometheus_range(
                promql, window["start_at"], window["end_at"], step
            )
        if path == "/api/prometheus/query":
            promql = params.get("promql", [None])[0]
            if not promql:
                raise ValueError("promql is required")
            return query_prometheus_instant(promql)
        if path == "/api/loki/query_range":
            window = query_window(params)
            logql = params.get("logql", [None])[0]
            if not logql:
                raise ValueError("logql is required")
            return query_loki_range(
                logql, window["start_at"], window["end_at"], window["limit"]
            )
        if path == "/api/loki/facets":
            window = query_window(params)
            return query_loki_facets(window["start_at"], window["end_at"])
        if path == "/api/tempo/search":
            window = query_window(params)
            traceql = params.get("q", ["{}"])[0]
            start_epoch = str(int(datetime.fromisoformat(window["start_at"]).timestamp()))
            end_epoch = str(int(datetime.fromisoformat(window["end_at"]).timestamp()))
            return query_tempo_search(traceql, start_epoch, end_epoch, window["limit"])
        if path == "/api/tempo/trace":
            return query_tempo_trace(params.get("trace_id", [""])[0])
        if path == "/api/kubernetes/pod-health":
            namespaces = params.get("namespace", ["app", "data", "pipeline"])
            return [pod_phase_summary(namespace) for namespace in namespaces]
        if path == "/api/kubernetes/workload-events":
            namespaces = params.get("namespace", ["app", "data", "pipeline"])
            events = []
            for namespace in namespaces:
                events.extend(workload_events(namespace))
            return events
        if path == "/api/kubernetes/deploy-events":
            namespaces = params.get("namespace", ["app", "data", "pipeline"])
            events = []
            for namespace in namespaces:
                events.extend(deploy_events(namespace))
            return events
        prefix = "/api/internal/incidents/"
        suffix = "/evidence/latest"
        if path.startswith(prefix) and path.endswith(suffix):
            incident_id = path[len(prefix) : -len(suffix)]
            if not incident_id or "/" in incident_id:
                raise ValueError("invalid incident id")
            return query_database(SNAPSHOT_SQL, {"incident_id": incident_id})
        raise ValueError("dashboard API path is not allowed")


def forward_incident_rca(incident_id: str) -> tuple[int, bytes]:
    """Forward the sole dashboard write-like action to the Operations API.

    The endpoint only creates an RCA response from an existing snapshot. It
    never accepts browser-provided Evidence or database credentials.
    """
    base_url = os.environ.get(OPERATIONS_API_URL_ENV)
    if not base_url:
        raise RuntimeError(f"set {OPERATIONS_API_URL_ENV} first")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/internal/incidents/{quote(incident_id, safe='')}/rca",
        method="POST",
        headers={"Accept": "application/json", "Content-Length": "0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def query_window(params: dict[str, list[str]]) -> dict[str, str]:
    try:
        start_at = parse_timestamp(params["start_at"][0])
        end_at = parse_timestamp(params["end_at"][0])
    except KeyError as error:
        raise ValueError("start_at and end_at are required") from error
    if start_at > end_at:
        raise ValueError("start_at must not be after end_at")
    raw_limit = params.get("limit", ["100"])[0]
    if not raw_limit.isdecimal() or not 1 <= int(raw_limit) <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    return {"start_at": start_at, "end_at": end_at, "limit": raw_limit}


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8080), DashboardHandler).serve_forever()
