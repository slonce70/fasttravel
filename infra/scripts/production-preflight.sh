#!/usr/bin/env bash
# FastTravel production preflight.
#
# Local/CI-safe checks that the deploy surface is internally consistent before
# a VPS cutover: compose overlays, workflow syntax, dashboard JSON, required env
# names, stale metric strings, and live health/Prometheus checks when the local
# stack is running.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-"$ROOT/.env"}"
STRICT_ENV="${STRICT_ENV:-0}"

failures=0

ok() { printf 'ok   %s\n' "$*"; }
warn() { printf 'warn %s\n' "$*" >&2; }
fail() {
    printf 'fail %s\n' "$*" >&2
    failures=$((failures + 1))
}

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        fail "missing required command: $1"
    fi
}

require_file() {
    if [[ ! -f "$ROOT/$1" ]]; then
        fail "missing required file: $1"
    else
        ok "found $1"
    fi
}

require_cmd docker
require_cmd jq
require_cmd curl

require_file docker-compose.yml
require_file docker-compose.prod.yml
require_file .env.example
require_file .github/CODEOWNERS
require_file .github/workflows/ci.yml
require_file .github/workflows/deploy-api.yml
require_file .github/workflows/deploy-web.yml
require_file .github/workflows/browser-smoke.yml
require_file .github/workflows/daily-backup.yml
require_file .github/workflows/security-scan.yml
require_file infra/grafana/dashboards/fasttravel-app.json
require_file infra/prometheus/prometheus.yml
require_file infra/prometheus/alertmanager.yml
require_file infra/scripts/secrets-bootstrap.sh
require_file infra/scripts/backup-restore-drill.sh

echo
echo "== compose =="
compose_json="$(
    cd "$ROOT"
    API_IMAGE=ghcr.io/example/fasttravel-api:sha-test \
        BOT_IMAGE=ghcr.io/example/fasttravel-bot:sha-test \
        SCHEDULER_IMAGE=ghcr.io/example/fasttravel-scheduler:sha-test \
        docker compose -f docker-compose.yml -f docker-compose.prod.yml config --format json
)"
echo "$compose_json" | jq empty
ok "prod compose renders as JSON"

for service in postgres redis prometheus grafana api; do
    ports_count="$(echo "$compose_json" | jq --arg svc "$service" '.services[$svc].ports // [] | length')"
    if [[ "$ports_count" != "0" ]]; then
        fail "$service publishes host ports in prod overlay"
    else
        ok "$service has no host ports in prod overlay"
    fi
done

for service in api bot scheduler; do
    image="$(echo "$compose_json" | jq -r --arg svc "$service" '.services[$svc].image')"
    if [[ "$image" != ghcr.io/example/fasttravel-*":sha-test" ]]; then
        fail "$service image does not respect CI image override: $image"
    else
        ok "$service image override works"
    fi
done

if echo "$compose_json" | jq -e '[.services[].image // "" | select(test(":(dev|latest)$"))] | length == 0' >/dev/null; then
    ok "prod compose has no :dev or :latest service images"
else
    echo "$compose_json" | jq -r '.services | to_entries[] | select((.value.image // "") | test(":(dev|latest)$")) | "\(.key)=\(.value.image)"' >&2
    fail "prod compose contains forbidden :dev or :latest image tags"
fi

nginx_ports="$(echo "$compose_json" | jq -r '.services.nginx.ports[]?.published' | sort | tr '\n' ' ')"
if [[ "$nginx_ports" != *"80"* || "$nginx_ports" != *"443"* ]]; then
    fail "nginx does not publish both 80 and 443 in prod overlay"
else
    ok "nginx publishes 80/443"
fi

echo
echo "== env contract =="
required_env=(
    ENVIRONMENT
    DATABASE_URL
    DATABASE_URL_SYNC
    REDIS_URL
    API_IMAGE
    BOT_IMAGE
    SCHEDULER_IMAGE
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHANNEL_ID
    GRAFANA_ADMIN_PASSWORD
)
for name in "${required_env[@]}"; do
    if ! grep -q "^${name}=" "$ROOT/.env.example"; then
        fail ".env.example missing $name"
    else
        ok ".env.example includes $name"
    fi
done

if [[ -f "$ENV_FILE" ]]; then
    ok "env file exists: $ENV_FILE"
    if [[ "$STRICT_ENV" == "1" ]] && ! grep -q '^ENVIRONMENT=prod' "$ENV_FILE"; then
        fail "STRICT_ENV=1 requires ENVIRONMENT=prod in $ENV_FILE"
    fi
    if grep -Eq '(_change_me|fasttravel_dev|GRAFANA_ADMIN_PASSWORD=admin$)' "$ENV_FILE"; then
        if [[ "$STRICT_ENV" == "1" ]] || grep -q '^ENVIRONMENT=prod' "$ENV_FILE"; then
            fail "$ENV_FILE contains dev/default secret markers"
        else
            warn "$ENV_FILE contains dev/default secret markers (allowed outside prod strict mode)"
        fi
    fi
    if [[ "$STRICT_ENV" == "1" ]] || grep -q '^ENVIRONMENT=prod' "$ENV_FILE"; then
        for name in TELEGRAM_BOT_TOKEN TELEGRAM_CHANNEL_ID API_IMAGE BOT_IMAGE SCHEDULER_IMAGE ALERTMANAGER_WEBHOOK_SECRET; do
            if ! grep -Eq "^${name}=.+" "$ENV_FILE"; then
                fail "prod env missing non-empty $name"
            fi
        done
    fi
else
    warn "env file not found: $ENV_FILE (set ENV_FILE=/path/to/.env.prod for strict prod checks)"
fi

echo
echo "== workflows and dashboards =="
if grep -Eq '@YOUR_USERNAME|TODO\(setup\)' "$ROOT/.github/CODEOWNERS"; then
    fail "CODEOWNERS still contains setup placeholders"
else
    ok "CODEOWNERS has concrete owners"
fi

while IFS= read -r workflow_ref; do
    workflow_ref="${workflow_ref#\`}"
    workflow_ref="${workflow_ref%\`}"
    if [[ ! -f "$ROOT/.github/workflows/$workflow_ref" ]]; then
        fail ".github/README.md references missing workflow: $workflow_ref"
    fi
done < <(grep -Eo '`[^`]+\.yml`' "$ROOT/.github/README.md" | sort -u)
ok ".github/README.md workflow references are present"

if command -v ruby >/dev/null 2>&1; then
    (
        cd "$ROOT"
        ruby -e 'require "yaml"; Dir[".github/workflows/*.yml"].each { |f| YAML.load_file(f) }'
    )
    ok "GitHub workflow YAML parses"
else
    warn "ruby not found; skipped workflow YAML parse"
fi

require_workflow_contains() {
    local file="$1"
    local pattern="$2"
    local description="$3"
    if grep -Eq -- "$pattern" "$ROOT/$file"; then
        ok "$description"
    else
        fail "$description"
    fi
}

require_workflow_contains ".github/workflows/deploy-api.yml" "DEPLOY_SSH_HOST" "deploy-api checks VPS host secret"
require_workflow_contains ".github/workflows/deploy-api.yml" "DEPLOY_SSH_USER" "deploy-api checks VPS user secret"
require_workflow_contains ".github/workflows/deploy-api.yml" "DEPLOY_SSH_KEY" "deploy-api checks VPS key secret"
require_workflow_contains ".github/workflows/deploy-api.yml" "GHCR_PULL_TOKEN" "deploy-api passes GHCR pull token to VPS"
require_workflow_contains ".github/workflows/deploy-api.yml" "docker login ghcr\\.io" "deploy-api logs VPS into GHCR before pull"
require_workflow_contains ".github/workflows/deploy-api.yml" "alembic upgrade head" "deploy-api runs migrations before recreate"
require_workflow_contains ".github/workflows/deploy-api.yml" "DEPLOY_NOTIFY_WEBHOOK" "deploy-api has failure webhook wiring"
require_workflow_contains ".github/workflows/deploy-api.yml" "apps/shared/\\*\\*" "deploy-api triggers when shared code changes"
require_workflow_contains ".github/workflows/deploy-api.yml" "production-preflight\\.sh" "deploy-api runs production preflight after recreate"
require_workflow_contains ".github/workflows/security-scan.yml" "exit-code: \"1\"" "security scan fails on high/critical Trivy findings"
require_workflow_contains ".github/workflows/deploy-web.yml" "CLOUDFLARE_ACCOUNT_ID" "deploy-web checks Cloudflare account secret"
require_workflow_contains ".github/workflows/deploy-web.yml" "CLOUDFLARE_API_TOKEN" "deploy-web checks Cloudflare token secret"
require_workflow_contains ".github/workflows/deploy-web.yml" "NEXT_PUBLIC_API_URL" "deploy-web passes build-time API URL"
require_workflow_contains ".github/workflows/deploy-web.yml" "pnpm cf:build" "deploy-web builds OpenNext output"
require_workflow_contains ".github/workflows/deploy-web.yml" "wrangler deploy .*--dry-run" "deploy-web dry-runs Worker bundle"
require_workflow_contains ".github/workflows/deploy-web.yml" "WEB_E2E_BASE_URL" "deploy-web can smoke deployed frontend"
require_workflow_contains ".github/workflows/ci.yml" "browser-smoke-local" "CI runs local browser-smoke job"
require_workflow_contains ".github/workflows/ci.yml" "python -m scripts\\.seed_e2e" "CI seeds browser-smoke data through API script"
require_workflow_contains ".github/workflows/ci.yml" "FASTTRAVEL_ALLOW_E2E_SEED" "CI opts into browser-smoke fixture seed"
require_workflow_contains ".github/workflows/ci.yml" "pnpm test:e2e" "CI executes Playwright browser smoke"
require_workflow_contains ".github/workflows/browser-smoke.yml" "WEB_E2E_BASE_URL" "browser-smoke targets deployed frontend URL"
require_workflow_contains ".github/workflows/daily-backup.yml" "BACKUP_SSH_USER" "daily-backup checks backup SSH user secret"
require_workflow_contains ".github/workflows/daily-backup.yml" "BACKUP_SSH_KEY" "daily-backup checks backup SSH key secret"
require_workflow_contains ".github/workflows/daily-backup.yml" "R2_ACCESS_KEY_ID" "daily-backup checks R2 access key secret"
require_workflow_contains ".github/workflows/daily-backup.yml" "R2_SECRET_ACCESS_KEY" "daily-backup checks R2 secret key"
require_workflow_contains ".github/workflows/daily-backup.yml" "-f docker-compose\\.yml -f docker-compose\\.prod\\.yml exec -T postgres" "daily-backup uses prod compose overlay"
require_workflow_contains ".github/workflows/daily-backup.yml" "pg_dump -U .*POSTGRES_USER.* -d .*POSTGRES_DB" "daily-backup uses env-provided database identity"
require_workflow_contains "infra/scripts/secrets-bootstrap.sh" "ALERTMANAGER_WEBHOOK_SECRET" "secrets bootstrap creates alert webhook secret"
require_workflow_contains "infra/scripts/secrets-bootstrap.sh" "infra/prometheus/\\.webhook_secret" "secrets bootstrap writes AlertManager secret file"
require_workflow_contains "infra/systemd/fasttravel-stack.service" "-f docker-compose\\.yml -f docker-compose\\.prod\\.yml up -d" "systemd stack uses base compose plus prod overlay"
require_workflow_contains "infra/systemd/fasttravel-snapshot.service" "-f docker-compose\\.yml -f docker-compose\\.prod\\.yml exec -T scheduler python -m src\\.jobs\\.snapshot_farvater" "systemd snapshot runs the real Farvater snapshot module"
require_workflow_contains "infra/systemd/fasttravel-keepalive.service" "-f docker-compose\\.yml -f docker-compose\\.prod\\.yml exec -T postgres" "systemd keepalive uses base compose plus prod overlay"
require_workflow_contains "infra/cloud-init.yml" "cd /opt/fasttravel \\|\\| exit 0" "cloud-init healthcheck waits for repo checkout"
require_workflow_contains "infra/cloud-init.yml" "-f docker-compose\\.yml -f docker-compose\\.prod\\.yml exec -T api" "cloud-init healthcheck uses internal API container health"
require_workflow_contains "infra/cloud-init.yml" "apache2-utils" "cloud-init installs htpasswd tooling for Grafana basic-auth"
require_workflow_contains "docker-compose.prod.yml" "/etc/nginx/\\.htpasswd-grafana:/etc/nginx/\\.htpasswd-grafana:ro" "prod nginx mounts Grafana htpasswd file"
require_workflow_contains "infra/nginx/fasttravel.conf" "server_name api\\.fasttravel\\.com\\.ua" "prod nginx serves the API host"
require_workflow_contains "infra/nginx/fasttravel.conf" "ssl_certificate +/etc/letsencrypt/live/api\\.fasttravel\\.com\\.ua/fullchain\\.pem" "prod nginx has explicit API certificate path"
require_workflow_contains "infra/nginx/fasttravel.conf" "ssl_certificate_key +/etc/letsencrypt/live/api\\.fasttravel\\.com\\.ua/privkey\\.pem" "prod nginx has explicit API private key path"
require_workflow_contains "infra/nginx/fasttravel.conf" "location = /health" "prod nginx proxies FastAPI health without /api prefix"
require_workflow_contains "infra/SETUP.md" "https://api\\.<your-domain>/health" "setup verifies the API health host and path"
require_workflow_contains ".github/README.md" "api\\.fasttravel\\.com\\.ua" "GitHub docs describe API host split"
require_workflow_contains "apps/web/README.md" "Worker should not own the API host" "web docs separate frontend and API hosts"
require_workflow_contains "infra/SETUP.md" "certbot certonly --standalone" "setup uses standalone certbot for container nginx"
require_workflow_contains "infra/SETUP.md" "docker stop ft_nginx" "setup documents certbot renewal pre-hook"
require_workflow_contains "infra/SETUP.md" "docker start ft_nginx" "setup documents certbot renewal post-hook"

if rg -n 'certbot --nginx|sites-available|sites-enabled|brotli[[:space:]]+on|brotli_types|libnginx-mod-http-brotli|python3-certbot-nginx' \
    "$ROOT/infra" "$ROOT/docs" "$ROOT/README.md" \
    -g '!infra/scripts/production-preflight.sh' \
    -g '!docs/superpowers/plans/**' >/tmp/fasttravel-preflight-nginx-stale.txt; then
    cat /tmp/fasttravel-preflight-nginx-stale.txt >&2
    fail "stale host-nginx/certbot/brotli production strings found"
else
    ok "no stale host-nginx/certbot/brotli production strings found"
fi

api_seed_opt_in="$(
    cd "$ROOT"
    FASTTRAVEL_ALLOW_E2E_SEED=1 docker compose config --format json |
        jq -r '.services.api.environment.FASTTRAVEL_ALLOW_E2E_SEED // ""'
)"
if [[ "$api_seed_opt_in" != "1" ]]; then
    fail "docker compose does not pass FASTTRAVEL_ALLOW_E2E_SEED into api service"
else
    ok "docker compose passes e2e seed opt-in to api"
fi

jq empty "$ROOT/infra/grafana/dashboards/fasttravel-app.json"
ok "Grafana dashboard JSON parses"

if rg -n 'fasttravel_snapshot_seconds|fasttravel_deals_detected_total|pg_stat_user_tables|fasttravel_mv_refresh_seconds|snapshot_stub|fasttravel_ua|TG_BOT_TOKEN|@YOUR_USERNAME|TODO\(setup\)|nightly-sitemap|docs/outreach|YOUR_NAME|YOUR_EMAIL|YOUR_PHONE|ORACLE_RESERVED_IP|Підняти весь стек|запустити весь стек|Frontend агент|app-track agent|apps/bot/src/publishers|apps/api/src/routers/sitemap.py|/calendar endpoint ignores|ADRs to add|Cloudflare Pages|DNS\+Pages|R2 / Pages' \
    "$ROOT" \
    -g '!apps/web/.next/**' \
    -g '!node_modules/**' \
    -g '!**/tests/**' \
    -g '!infra/scripts/production-preflight.sh' \
    -g '!*.lock' \
    -g '!docs/superpowers/plans/**' >/tmp/fasttravel-preflight-stale.txt; then
    cat /tmp/fasttravel-preflight-stale.txt >&2
    fail "stale production strings found"
else
    ok "no stale production strings found"
fi

echo
echo "== optional live checks =="
if curl -fsS --max-time 3 http://localhost:8000/health >/tmp/fasttravel-health.json; then
    jq -e '.status == "ok" and .db == "ok" and .redis == "ok"' /tmp/fasttravel-health.json >/dev/null
    ok "local API /health is ok"
else
    warn "local API not reachable; skipped live /health"
fi

if fixture_rows="$(
    cd "$ROOT"
    docker compose exec -T postgres psql -U "${POSTGRES_USER:-fasttravel}" -d "${POSTGRES_DB:-fasttravel}" -Atc "
        SELECT
            (SELECT count(*) FROM destinations WHERE region_slug LIKE 'ci-e2e-%') +
            (SELECT count(*) FROM hotels WHERE canonical_slug LIKE 'ci-e2e-%') +
            (SELECT count(*) FROM hotel_operator_mapping WHERE external_id LIKE 'ci-e2e-%') +
            (
                SELECT count(*)
                FROM price_observations
                WHERE raw_payload->>'fixture' = 'ci-e2e'
                   OR deep_link LIKE '%/ci-e2e-%'
            ) +
            (
                SELECT count(*)
                FROM deals
                WHERE deep_link LIKE '%/ci-e2e-%'
                   OR hotel_id IN (
                       SELECT id FROM hotels WHERE canonical_slug LIKE 'ci-e2e-%'
                   )
            );
    " 2>/tmp/fasttravel-preflight-db.err
)"; then
    if [[ "$fixture_rows" != "0" ]]; then
        fail "live DB contains ci-e2e fixture rows: $fixture_rows"
    else
        ok "live DB has no ci-e2e fixture rows"
    fi
else
    warn "local Postgres not reachable; skipped fixture-row check"
    if [[ -s /tmp/fasttravel-preflight-db.err ]]; then
        cat /tmp/fasttravel-preflight-db.err >&2
    fi
fi

if curl -fsS --max-time 3 http://localhost:9090/api/v1/targets >/tmp/fasttravel-targets.json; then
    down_targets="$(jq '[.data.activeTargets[] | select(.health != "up")] | length' /tmp/fasttravel-targets.json)"
    if [[ "$down_targets" != "0" ]]; then
        jq '.data.activeTargets[] | {job:.labels.job, health, lastError}' /tmp/fasttravel-targets.json >&2
        fail "Prometheus has down targets"
    else
        ok "Prometheus targets are up"
    fi
else
    warn "Prometheus not reachable; skipped target health"
fi

echo
if [[ "$failures" -gt 0 ]]; then
    echo "production preflight failed: $failures issue(s)" >&2
    exit 1
fi

echo "production preflight passed"
