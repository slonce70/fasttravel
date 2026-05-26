#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR" || exit 1

mkdir -p logs
LOG_PATH="logs/overnight-refill-$(date -u +%Y%m%dT%H%M%SZ).log"
exec > >(tee -a "$LOG_PATH") 2>&1

stage() {
  echo
  echo "===== $(date '+%Y-%m-%dT%H:%M:%S%z') :: $* ====="
}

run_stage() {
  local name="$1"
  shift
  stage "$name"
  "$@"
  local rc=$?
  echo "===== $(date '+%Y-%m-%dT%H:%M:%S%z') :: $name finished rc=$rc ====="
  return 0
}

redis_get() {
  docker compose exec -T redis redis-cli GET "$1" 2>/dev/null | tr -d '\r'
}

wait_for_service_health() {
  local service="$1"
  local tries="${2:-60}"
  for _ in $(seq 1 "$tries"); do
    local status
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "ft_${service}" 2>/dev/null || true)"
    if [[ "$status" == "healthy" || "$status" == "running" ]]; then
      echo "$service is $status"
      return 0
    fi
    sleep 5
  done
  echo "$service did not become healthy in time"
  return 1
}

stage "overnight refill started"
echo "log=$LOG_PATH"
date
date -u

stage "keeping Telegram writers stopped"
docker compose stop bot scheduler || true
docker compose up -d postgres redis api
wait_for_service_health postgres 60 || true
wait_for_service_health redis 60 || true

START_UTC_DAY="$(date -u +%Y%m%d)"
COUNTER_KEY="scheduler:farvater:daily_count:${START_UTC_DAY}"
CURRENT_COUNTER="$(redis_get "$COUNTER_KEY")"
CURRENT_COUNTER="${CURRENT_COUNTER:-0}"
echo "current Farvater telemetry counter ${COUNTER_KEY}=${CURRENT_COUNTER}"
echo "local daily cap is disabled; counter is telemetry only"

run_stage "long-tail sitemap ingest for all supported-country sitemap hotels" \
  docker compose run --rm --no-deps \
  -e FT_FARVATER_CONCURRENCY=80 \
  -e FT_FARVATER_HTTP_CONCURRENCY=80 \
  -e FT_FARVATER_HTTP_MIN_INTERVAL_S=0 \
  -e FT_FARVATER_HTTP_TIMEOUT_S=20 \
  -e FT_FARVATER_REQUEST_DELAY_S=0 \
  -e FT_SITEMAP_INGEST_CONCURRENCY=80 \
  -e FT_SITEMAP_INGEST_DELAY_S=0 \
  scheduler \
  python -c 'import asyncio; from src.jobs.sitemap_long_tail import sitemap_long_tail_ingest_resilient; print(asyncio.run(sitemap_long_tail_ingest_resilient(cap=None)))'

run_stage "full price snapshot for all catalogued supported-country hotels" \
  docker compose run --rm --no-deps \
  -e FT_SNAPSHOT_MAX_HOTELS_PER_COUNTRY=0 \
  -e FT_SNAPSHOT_MAX_RUNTIME_MINUTES=0 \
  -e FT_FARVATER_CONCURRENCY=80 \
  -e FT_FARVATER_HTTP_CONCURRENCY=80 \
  -e FT_FARVATER_HTTP_MIN_INTERVAL_S=0 \
  -e FT_FARVATER_HTTP_TIMEOUT_S=20 \
  -e FT_FARVATER_REQUEST_DELAY_S=0 \
  scheduler python -m src.jobs.snapshot_farvater

run_stage "refresh materialized views" \
  docker compose run --rm --no-deps scheduler \
  python -c 'import asyncio; from src.jobs.refresh_views import refresh_views; asyncio.run(refresh_views())'

run_stage "refresh baselines" \
  docker compose run --rm --no-deps scheduler \
  python -c 'import asyncio; from src.jobs.refresh_baselines import refresh_baselines; print(asyncio.run(refresh_baselines()))'

run_stage "cold-start deal detection without Telegram posting" \
  bash -lc "docker compose exec -T redis redis-cli SET flag:cold_start true && docker compose run --rm --no-deps scheduler python -c 'import asyncio; from src.jobs.detect_deals import detect_deals; print(asyncio.run(detect_deals()))'"

run_stage "final counts" \
  docker compose exec -T postgres psql -U fasttravel -d fasttravel -c \
  "select count(*) as hotels, count(*) filter (where has_active_prices) as priced_hotels from hotels;
   select count(*) as price_observations from price_observations;
   select count(*) as current_prices from current_prices;
   select count(*) as hotel_calendar_prices from hotel_calendar_prices;
   select count(*) as deals, count(*) filter (where telegram_msg_id is not null) as posted from deals;
   select source, status, rows_inserted, started_at, finished_at, left(error_text, 160) as error
     from scrape_runs order by started_at desc limit 10;"

stage "overnight refill finished"
echo "Farvater counter $(date -u +%Y%m%d)=$(redis_get "scheduler:farvater:daily_count:$(date -u +%Y%m%d)")"
docker compose ps api bot scheduler postgres redis || true
