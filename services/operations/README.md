# Operations Service

The operations service owns cross-service anomaly detection and, in later
phases, incident correlation and evidence generation. Business services do not
depend on it.

## Current scope

- Evaluate an ordered metric time series.
- Build a rolling baseline from accepted, non-anomalous points.
- Calculate Z-score, robust MAD score, and point-to-point change rate.
- Require consecutive breached windows before declaring an anomaly.
- Expose the calculation through `POST /internal/anomalies/evaluate`.
- Receive Alertmanager webhooks through `POST /internal/alerts/alertmanager`.
- Normalize Alertmanager labels and annotations into the alert contract used by
  persistence and Incident correlation.
- Correlate normalized alerts through `POST /internal/incidents/correlate` using
  a time window, service identity, Pod identity, and declared dependencies.
- Persist normalized Alerts and generated Incident candidates in PostgreSQL.
  The Alertmanager endpoint stores the received Alerts, reloads nearby firing
  Alerts, runs correlation, then creates or refreshes the matching Incidents.

Prometheus querying, scheduled evaluation, real dependency configuration, and
Bedrock integration are intentionally outside this slice.

## Default policy

| Setting | Default |
|---|---:|
| Baseline window | 60 samples |
| Minimum baseline | 30 samples |
| Z-score threshold | 3.0 |
| MAD threshold | 3.5 |
| Change-rate threshold | 50% |
| Consecutive windows | 3 |

These are provisional engineering defaults. They must be calibrated with
historical Prometheus data and controlled k6 scenarios before production use.

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8011
```

Apply the Operations-owned schema once, then enable persistence before routing
Alertmanager webhooks to this service:

```bash
psql "$DATABASE_URL" -f schema.sql
export OPERATIONS_DATABASE_ENABLED=true
```

Without `OPERATIONS_DATABASE_ENABLED=true`, the pure analysis and manual
correlation endpoints remain available, while the webhook endpoint returns
`503` rather than accepting alerts that cannot be retained.

```bash
pytest -q
```
