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

Prometheus querying, scheduled evaluation, persistence, incident correlation,
and Bedrock integration are intentionally outside this first slice.

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

```bash
pytest -q
```
