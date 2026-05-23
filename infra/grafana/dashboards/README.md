# Grafana dashboards

Three dashboards are wired up:

| Dashboard | Source | UID |
|---|---|---|
| Node Exporter Full (CPU/RAM/disk/network) | Grafana.com [#1860](https://grafana.com/grafana/dashboards/1860-node-exporter-full/) | `rYdddlPWk` |
| PostgreSQL Database (postgres_exporter) | Grafana.com [#9628](https://grafana.com/grafana/dashboards/9628-postgresql-database/) | `000000039` |
| FastTravel app (custom) | This repo (`fasttravel-app.json`) | `fasttravel-app` |

## Why this layout instead of bundling JSON

The community dashboards (1860, 9628) are 5000+ line JSON files that change
across versions. Shipping a hand-edited copy means they go stale and silently
break on a Grafana upgrade. Instead, we use Grafana's `provisioning` feature
to load them by ID from grafana.com at startup — always the latest version
compatible with the installed Grafana.

Only `fasttravel-app.json` lives in this repo (it's our own).

## Wiring it up in docker-compose

The Grafana container in `docker-compose.prod.yml` should mount the
provisioning directory:

```yaml
grafana:
  image: grafana/grafana:11.3.0
  volumes:
    - ./infra/grafana/provisioning:/etc/grafana/provisioning:ro
    - ./infra/grafana/dashboards:/var/lib/grafana/dashboards:ro
    - grafana-data:/var/lib/grafana
  environment:
    GF_INSTALL_PLUGINS: ""
    GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH: /var/lib/grafana/dashboards/fasttravel-app.json
```

`provisioning/datasources/prometheus.yml` registers Prometheus as the default
data source. `provisioning/dashboards/fasttravel.yml` tells Grafana to scan
`/var/lib/grafana/dashboards/*.json` for dashboards on startup. Community
dashboards (1860, 9628) are loaded manually via UI → Dashboards → Import →
type the ID. This is a 30-second one-time step the runbook covers.

## fasttravel-app.json panels

1. Snapshot job duration (last 24 h) — Prometheus histogram from APScheduler.
2. Deals detected per hour — `sum(rate(fasttravel_deals_detected_total[1h]))`.
3. `price_observations` row count — `pg_stat_user_tables` for the partitioned table.
4. MV refresh duration (last 6 h) — `fasttravel_mv_refresh_seconds`.

Custom metrics expected in the FastAPI/scheduler code:

- `fasttravel_snapshot_seconds` (histogram)
- `fasttravel_deals_detected_total` (counter)
- `fasttravel_mv_refresh_seconds{view="current_prices|hotel_calendar_prices|price_baselines"}` (histogram)

If those metrics aren't published yet, the panels render "No data" but don't
break.
