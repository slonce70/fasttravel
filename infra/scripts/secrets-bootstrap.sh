#!/usr/bin/env bash
# Bootstrap production secrets for FastTravel.
#
# Generates a fresh .env file with cryptographically random passwords for
# Postgres, Grafana, etc. Writes to ./.env.prod and 0600-chmods it so
# only the deploy user can read it.
#
# Usage:
#   ./infra/scripts/secrets-bootstrap.sh [output-path]
#
# Default output: ./.env.prod
# Refuses to overwrite an existing file unless you pass --force.
#
# Variables we MUST rotate before prod:
#   POSTGRES_PASSWORD     — DB superuser
#   GRAFANA_ADMIN_PASSWORD — Grafana admin
#
# Variables we keep as placeholders for the operator to fill in:
#   API_IMAGE / BOT_IMAGE / SCHEDULER_IMAGE, TELEGRAM_BOT_TOKEN,
#   ITTOUR_API_TOKEN, TBO_USERNAME / TBO_PASSWORD, SENTRY_DSN — these come
#   from CI, registries, or third parties, not from openssl.

set -euo pipefail

OUTPUT="${1:-.env.prod}"
WEBHOOK_SECRET_PATH="${WEBHOOK_SECRET_PATH:-infra/prometheus/.webhook_secret}"
FORCE=false
for arg in "$@"; do
    [[ "$arg" == "--force" ]] && FORCE=true
done

if [[ -e "$OUTPUT" ]] && [[ "$FORCE" != true ]]; then
    echo "Refusing to overwrite existing $OUTPUT — pass --force to rotate." >&2
    exit 1
fi

# 32 bytes from /dev/urandom, base64-encoded, strip = / + that break shell.
gen_secret() {
    openssl rand -base64 32 | tr -d '=+/\n'
}

POSTGRES_PASSWORD="$(gen_secret)"
GRAFANA_ADMIN_PASSWORD="$(gen_secret)"
ALERTMANAGER_WEBHOOK_SECRET="$(gen_secret)"

cat > "$OUTPUT" <<EOF
# =============================================================================
# FastTravel — PRODUCTION environment (generated $(date -u +%Y-%m-%dT%H:%M:%SZ))
# DO NOT commit. DO NOT share over Slack/email — use a password manager.
# =============================================================================

# --- Environment ---
ENVIRONMENT=prod
LOG_LEVEL=INFO

# --- Postgres ---
POSTGRES_USER=fasttravel
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=fasttravel
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://fasttravel:${POSTGRES_PASSWORD}@postgres:5432/fasttravel
DATABASE_URL_SYNC=postgresql+psycopg://fasttravel:${POSTGRES_PASSWORD}@postgres:5432/fasttravel

# --- Redis ---
REDIS_URL=redis://redis:6379/0

# --- API ---
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=https://fasttravel.com.ua,https://www.fasttravel.com.ua

# --- Images (FILL IN from deploy workflow / GHCR tags) ---
API_IMAGE=
BOT_IMAGE=
SCHEDULER_IMAGE=

# --- Telegram (FILL IN before launch) ---
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID=

# --- ittour API (FILL IN when access granted) ---
ITTOUR_API_BASE=https://api.ittour.com.ua
ITTOUR_API_TOKEN=

# --- TBO Holidays (FILL IN when access granted) ---
TBO_API_BASE=https://api.tbotechnology.in/TBOHolidays_HotelAPI
TBO_USERNAME=
TBO_PASSWORD=

# --- Observability (FILL IN before launch) ---
SENTRY_DSN=
SENTRY_TRACES_SAMPLE_RATE=0.05

# --- AlertManager -> bot webhook ---
ALERTMANAGER_WEBHOOK_SECRET=${ALERTMANAGER_WEBHOOK_SECRET}

# --- Grafana ---
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}
EOF

chmod 600 "$OUTPUT"
mkdir -p "$(dirname "$WEBHOOK_SECRET_PATH")"
printf '%s\n' "$ALERTMANAGER_WEBHOOK_SECRET" > "$WEBHOOK_SECRET_PATH"
chmod 600 "$WEBHOOK_SECRET_PATH"

echo "Wrote $OUTPUT (0600)."
echo "Wrote $WEBHOOK_SECRET_PATH (0600)."
echo
echo "Next steps:"
echo "  1. Fill in API_IMAGE / BOT_IMAGE / SCHEDULER_IMAGE and external secrets."
echo "  2. Run: ENV_FILE=$OUTPUT STRICT_ENV=1 ./infra/scripts/production-preflight.sh"
echo "  3. Copy $OUTPUT to the prod host as .env: scp $OUTPUT user@host:/opt/fasttravel/.env"
echo "  4. Run: docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
echo "  5. Verify /health and Prometheus/Grafana after cutover."
