# systemd units

Install on the Oracle VM from the repo root:

```bash
sudo cp \
    infra/systemd/fasttravel-stack.service \
    infra/systemd/fasttravel-keepalive.service \
    infra/systemd/fasttravel-keepalive.timer \
    /etc/systemd/system/
sudo systemctl daemon-reload

# Stack (starts docker-compose at boot)
sudo systemctl enable --now fasttravel-stack.service

# Hourly keepalive (anti-reclamation insert)
sudo systemctl enable --now fasttravel-keepalive.timer
```

Verify timers are scheduled:

```bash
systemctl list-timers --all | grep fasttravel
journalctl -u fasttravel-keepalive.service -n 50 --no-pager
```

The production compose file is an overlay. All units intentionally call:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ...
```

Do not run `docker-compose.prod.yml` by itself; it does not define standalone
images/build contexts for every service.

## Price snapshots

Price snapshots are owned by APScheduler in `apps/scheduler/src/main.py`.
Do not add or enable a host systemd timer/service for `snapshot_farvater`;
production must have only one 06:00/18:00 Europe/Kyiv snapshot owner.
