#!/usr/bin/env bash
# Runs once on first container start (empty data dir).
# Creates required extensions in the application database.
#
# Notes:
#   - pg_cron extension lives in whichever DB matches cron.database_name
#     in postgresql.conf (we set it to 'fasttravel').
#   - pg_partman creates its catalog tables in a dedicated 'partman' schema.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE EXTENSION IF NOT EXISTS btree_gin;
    CREATE EXTENSION IF NOT EXISTS pg_cron;
    CREATE SCHEMA IF NOT EXISTS partman;
    CREATE EXTENSION IF NOT EXISTS pg_partman SCHEMA partman;
EOSQL
