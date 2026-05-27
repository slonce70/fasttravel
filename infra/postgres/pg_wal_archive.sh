#!/usr/bin/env bash
# pg_wal_archive — invoked by Postgres archive_command (one call per WAL
# segment). Pushes the segment to Cloudflare R2 via rclone.
#
# Operator install (audit Quarter #15):
#   1. Copy this file to the VPS:  /usr/local/bin/pg_wal_archive.sh
#   2. chmod 755 /usr/local/bin/pg_wal_archive.sh
#   3. Configure rclone (~root/.config/rclone/rclone.conf) with the
#      same [r2] remote the daily-backup workflow uses.
#   4. Edit infra/postgres/postgresql.conf:
#        archive_mode    = on
#        archive_command = '/usr/local/bin/pg_wal_archive.sh "%p" "%f"'
#   5. docker compose -f docker-compose.yml -f docker-compose.prod.yml restart postgres
#   6. Verify:
#        docker compose exec postgres psql -U fasttravel -c \
#          'SELECT * FROM pg_stat_archiver;'
#      archived_count should climb; failed_count should stay at 0.
#
# Contract Postgres expects from archive_command:
#   - Exit 0 on success.
#   - Exit non-zero on failure; Postgres will retry the same segment
#     forever (commits eventually block when pg_wal/ fills up).
#   - Must not delete %p — Postgres manages segment lifecycle.
#
# Source path (%p) is relative to PGDATA, e.g. pg_wal/0000000100000000000000A1.
# Destination filename (%f) is the bare segment name.

set -euo pipefail

SRC="$1"   # %p — relative source path inside PGDATA
NAME="$2"  # %f — bare WAL segment filename
BUCKET="${R2_BUCKET:?R2_BUCKET env var required}"

# rclone's S3-compatible backend handles retries internally. --quiet
# keeps the postgres log tidy; failures will surface via stderr +
# pg_stat_archiver.failed_count.
rclone copyto --quiet --s3-no-check-bucket \
    "${SRC}" "r2:${BUCKET}/wal/${NAME}"
