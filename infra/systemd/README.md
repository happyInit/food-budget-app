# Operations daily report timer

The report is a one-shot command inside the already-running `operations-api`
container. It is intentionally not an in-process FastAPI scheduler.

## Runtime prerequisites

The EC2 Compose service `operations-api` must pass these values into the
container. Keep values in `/opt/mealbong-app/.env`; do not commit them.

```ini
DAILY_REPORT_ENABLED=true
DAILY_REPORT_SLACK_WEBHOOK_URL=<secret>
# Set only after the product/team agrees on the targets.
DAILY_REPORT_AVAILABILITY_SLO=
DAILY_REPORT_P95_LATENCY_MS_SLO=
```

Its `environment:` section must forward the four names above, using the same
`${NAME:-}` pattern as the existing Operations settings.

## Install on the dashboard EC2

Copy the two unit files to `/etc/systemd/system/`, then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mp-daily-report.timer
systemctl list-timers mp-daily-report.timer
```

The timer launches at 09:05 KST. The report window is fixed to 09:00 KST of
the preceding day through 08:59:59 KST of the current day.

Before enabling the timer, run the service once manually and verify that the
dedicated Slack channel receives the report:

```bash
sudo systemctl start mp-daily-report.service
sudo journalctl -u mp-daily-report.service -n 100 --no-pager
```
