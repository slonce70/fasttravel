# systemd units

Install on the Oracle VM:

```bash
sudo cp infra/systemd/*.service infra/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload

# Stack (starts docker-compose at boot)
sudo systemctl enable --now fasttravel-stack.service

# Twice-daily snapshot
sudo systemctl enable --now fasttravel-snapshot.timer

# Hourly keepalive (anti-reclamation insert)
sudo systemctl enable --now fasttravel-keepalive.timer
```

Verify timers are scheduled:

```bash
systemctl list-timers --all | grep fasttravel
journalctl -u fasttravel-snapshot.service -n 50 --no-pager
```

## Timezone note

`OnCalendar=*-*-* 06,18:00:00` uses the **host** timezone, which is set to
`Europe/Kyiv` by `cloud-init.yml`. Do **not** add `Timezone=` to the
OnCalendar line — that field requires systemd ≥ 252 and Ubuntu 22.04 ships
249.
