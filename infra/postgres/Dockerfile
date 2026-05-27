# Custom Postgres 16 image with pg_partman, pg_cron, pg_trgm, btree_gin.
#
# We use the Debian-based image (NOT alpine) because pg_partman and pg_cron
# are distributed as prebuilt .deb packages by the official PGDG apt repo.
# Building from source against alpine would require pulling the postgres
# source tree and recompiling — not worth the complexity for a free-tier MVP.
FROM postgres:16-bookworm

# hadolint ignore=DL3008
# DL3008 wants explicit apt-pinned versions; PGDG bumps the deb revision
# on every Postgres security release and uses arch-specific suffixes,
# which makes the pinned name unstable. Tracking the base image bump
# via Dependabot's docker ecosystem (.github/dependabot.yml) already
# enforces upstream-current packages. See audit "Hadolint findings (5)".
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-16-partman \
        postgresql-16-cron \
        postgresql-16-postgis-3 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# pg_cron requires shared_preload_libraries + restart.
# pg_partman background worker (pg_partman_bgw) is optional — we run
# create_parent() once in migrations and use pg_cron for maintenance.
COPY postgresql.conf /etc/postgresql/postgresql.conf
COPY init-extensions.sh /docker-entrypoint-initdb.d/10-init-extensions.sh

# Use our custom config file
CMD ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]
