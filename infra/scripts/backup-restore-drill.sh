#!/usr/bin/env bash
# Verify that a FastTravel PostgreSQL dump can be restored into a clean DB.
#
# Usage:
#   ./infra/scripts/backup-restore-drill.sh [dump.sql.gz]
#
# If no dump path is provided, the script creates a temporary dump from the
# local compose `postgres` service first. CI backup workflow passes the dump it
# just downloaded from the VPS before uploading it to R2.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DUMP_FILE="${1:-}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-fasttravel/postgres:16}"
RESTORE_CONTAINER="${RESTORE_CONTAINER:-ft_restore_drill_$(date -u +%Y%m%d%H%M%S)_$$}"
RESTORE_USER="${RESTORE_USER:-restore}"
RESTORE_PASSWORD="${RESTORE_PASSWORD:-restore}"
# Keep the default database name aligned with infra/postgres/postgresql.conf
# (`cron.database_name = 'fasttravel'`) so the custom image can initialize
# pg_cron during restore drills.
RESTORE_DB="${RESTORE_DB:-fasttravel}"
KEEP_DUMP="${KEEP_DUMP:-0}"

TMP_DIR=""

cleanup() {
    docker rm -f "$RESTORE_CONTAINER" >/dev/null 2>&1 || true
    if [[ -n "$TMP_DIR" && "$KEEP_DUMP" != "1" ]]; then
        rm -rf "$TMP_DIR"
    elif [[ -n "$TMP_DIR" ]]; then
        echo "kept temporary dump directory: $TMP_DIR"
    fi
}
trap cleanup EXIT

log() {
    printf '==> %s\n' "$*"
}

if ! command -v docker >/dev/null 2>&1; then
    echo "docker is required" >&2
    exit 1
fi

if [[ -z "$DUMP_FILE" ]]; then
    TMP_DIR="$(mktemp -d /tmp/fasttravel-restore-drill.XXXXXX)"
    DUMP_FILE="$TMP_DIR/fasttravel-local.sql.gz"
    log "creating temporary local dump from compose postgres"
    (
        cd "$ROOT"
        docker compose exec -T postgres \
            pg_dump -U "${POSTGRES_USER:-fasttravel}" \
            -d "${POSTGRES_DB:-fasttravel}" \
            --no-owner --clean --if-exists \
            | gzip -9 > "$DUMP_FILE"
    )
fi

if [[ ! -s "$DUMP_FILE" ]]; then
    echo "dump file is missing or empty: $DUMP_FILE" >&2
    exit 1
fi

log "validating gzip archive"
gzip -t "$DUMP_FILE"

if ! docker image inspect "$POSTGRES_IMAGE" >/dev/null 2>&1; then
    if [[ "$POSTGRES_IMAGE" == "fasttravel/postgres:16" ]]; then
        log "building $POSTGRES_IMAGE for pg_partman/pg_cron-compatible restore"
        docker build -q -t "$POSTGRES_IMAGE" "$ROOT/infra/postgres" >/dev/null
    else
        log "pulling $POSTGRES_IMAGE"
        docker pull "$POSTGRES_IMAGE" >/dev/null
    fi
fi

log "starting clean restore container $RESTORE_CONTAINER"
docker run -d --name "$RESTORE_CONTAINER" \
    -e POSTGRES_USER="$RESTORE_USER" \
    -e POSTGRES_PASSWORD="$RESTORE_PASSWORD" \
    -e POSTGRES_DB="$RESTORE_DB" \
    "$POSTGRES_IMAGE" >/dev/null

log "waiting for restore database"
for _ in $(seq 1 30); do
    if docker exec "$RESTORE_CONTAINER" pg_isready -U "$RESTORE_USER" -d "$RESTORE_DB" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
if ! docker exec "$RESTORE_CONTAINER" pg_isready -U "$RESTORE_USER" -d "$RESTORE_DB" >/dev/null 2>&1; then
    docker logs "$RESTORE_CONTAINER" >&2 || true
    echo "restore database did not become ready" >&2
    exit 1
fi

log "restoring dump with ON_ERROR_STOP"
if ! gzip -dc "$DUMP_FILE" | docker exec -i "$RESTORE_CONTAINER" \
    psql -v ON_ERROR_STOP=1 -U "$RESTORE_USER" -d "$RESTORE_DB" >/tmp/fasttravel-restore-drill-psql.log 2>&1; then
    cat /tmp/fasttravel-restore-drill-psql.log >&2
    exit 1
fi

table_count="$(
    docker exec "$RESTORE_CONTAINER" psql -At -U "$RESTORE_USER" -d "$RESTORE_DB" \
        -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';"
)"

if [[ "${table_count:-0}" -lt 1 ]]; then
    echo "restore completed but public schema has no tables" >&2
    exit 1
fi

log "restore drill passed; public table count: $table_count"
