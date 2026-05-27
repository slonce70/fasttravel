# FastTravel — production setup runbook

End-to-end: zero → live VM with HTTPS, Docker, monitoring, ready to receive
the application code. Budget: $0/month. Time: ~30 min once your Oracle
account exists.

---

## 0. Prerequisites on your workstation

```bash
# macOS:
brew install terraform oci-cli jq
# Linux:
sudo apt-get install -y terraform jq && \
  bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"
```

You will need:

- An email + a payment card (Oracle will not charge if you stay in Always Free).
- A domain you own (recommended `.com.ua`, ~250 UAH/year).
- A Cloudflare account (free tier).

---

## 1. Register an Oracle Cloud account (15 min, one-time)

1. Open <https://signup.cloud.oracle.com/> and sign up.
2. **Home region**: pick `eu-frankfurt-1` (or `eu-amsterdam-1`). This is permanent — choose carefully.
3. Verify your email, add a phone number, enter card details. Oracle does a small auth check; no money is taken.
4. Once you land in the Console, top-left menu → **Identity & Security → Compartments**. Confirm there's at least the root compartment with your tenancy name. For now you'll use the tenancy as your compartment.

### Capture the OCIDs

- Top-right avatar → click your **tenancy name** at the top → copy the long string after **OCID:** → that's your `tenancy_ocid`.
- Top-right avatar → **User Settings** → copy **OCID** → that's your `user_ocid`.

---

## 2. Generate Terraform API key (5 min)

```bash
mkdir -p ~/.oci
openssl genrsa -out ~/.oci/fasttravel_api_key.pem 2048
chmod 600  ~/.oci/fasttravel_api_key.pem
openssl rsa -pubout \
  -in  ~/.oci/fasttravel_api_key.pem \
  -out ~/.oci/fasttravel_api_key_public.pem
```

In the OCI Console:

1. **User Settings → Resources → API Keys → Add API Key**.
2. Choose **Paste Public Key** and paste the contents of `fasttravel_api_key_public.pem`.
3. After upload, copy the **Fingerprint** shown (e.g. `aa:bb:cc:...`).

---

## 3. SSH key for the VM (1 min)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/fasttravel_oracle -C "fasttravel-prod"
```

Two files appear: `fasttravel_oracle` (private — keep safe) and `fasttravel_oracle.pub` (public — Terraform installs this onto the VM).

---

## 4. Fill in `terraform.tfvars` (3 min)

```bash
cd infra/terraform
cp example.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars
```

Paste:

- `tenancy_ocid` and `user_ocid` from step 1.
- `fingerprint` from step 2.
- `private_key_path = "/Users/you/.oci/fasttravel_api_key.pem"` (absolute path).
- `compartment_ocid = <same as tenancy_ocid>` (for a fresh tenancy).
- `region = "eu-frankfurt-1"` (or whichever you picked).
- `ssh_public_key_path = "/Users/you/.ssh/fasttravel_oracle.pub"`.

---

## 5. Apply (5 min, +5 min for cloud-init)

```bash
terraform init
terraform plan -out=plan.out
terraform apply plan.out
```

Watch for `Apply complete!` and the outputs:

```
public_ip   = "129.213.x.x"
ssh_command = "ssh -i /Users/you/.ssh/fasttravel_oracle ubuntu@129.213.x.x"
```

### If apply fails with "Out of host capacity"

This is **expected** — A1.Flex in EU regions is constantly oversubscribed.

1. Re-run `terraform apply plan.out` a few times.
2. Edit `terraform.tfvars`, bump `availability_domain_index` to `1` then `2`, re-plan, re-apply.
3. If still nothing after an hour, try a fresh region (`uk-london-1`, `me-jeddah-1`). Region change requires recreating the tenancy.
4. Last resort: a community-known trick is to wrap `terraform apply` in a `while`-loop every 60 s (don't go faster — Oracle rate-limits).

---

## 6. Wait for cloud-init (~5 min after apply)

The VM exists but `apt update && apt upgrade -y && install Docker/certbot/...`
takes ~3-7 min. SSH in and check:

```bash
ssh -i ~/.ssh/fasttravel_oracle ubuntu@<public_ip>

# On the VM:
cloud-init status --wait        # blocks until done
cat /etc/fasttravel-bootstrap.completed
docker --version
docker compose version
ufw status
systemctl status fail2ban
```

Expected: all green, ufw shows 22/80/443 ALLOW, fail2ban active.

---

## 7. Cloudflare DNS (2 min)

In your Cloudflare dashboard → **Add a site** → enter your domain. After
NS-change is propagated (a few minutes):

1. **DNS → Records → Add record**: type `A`, name `api`, IPv4 = your Oracle Reserved IP, proxy status **Proxied** (orange cloud). The public web frontend (`@` / `www`) is attached to the Cloudflare Worker, not to the VPS.
2. **SSL/TLS → Overview**: set to **Full (strict)** once you've got a Let's Encrypt cert. For initial setup use **Full**.
3. **SSL/TLS → Edge Certificates**: enable **Always Use HTTPS**, **Automatic HTTPS Rewrites**, **HSTS** (only after you're sure HTTPS works — HSTS has a 6-month commit).

---

## 8. Provision Let's Encrypt cert for container nginx (5 min)

Production uses the nginx container from `docker-compose.prod.yml`, not host
nginx. Certbot runs on the host only to create/renew files under
`/etc/letsencrypt`, which the container mounts read-only.

```bash
# On the VM, before starting the compose nginx container:
sudo certbot certonly --standalone \
  -d api.<your-domain> \
  --email you@example.com --agree-tos --no-eff-email
```

If your API domain is not `api.fasttravel.com.ua`, edit
`infra/nginx/fasttravel.conf` in the repo checkout before starting the stack:

```bash
sudo -u fasttravel sed -i 's/api\.fasttravel\.com\.ua/api.<your-domain>/g' \
  /opt/fasttravel/infra/nginx/fasttravel.conf
```

### Grafana basic-auth

```bash
sudo htpasswd -c /etc/nginx/.htpasswd-grafana admin   # prompts for password
```

The file is mounted into the nginx container by `docker-compose.prod.yml`.

### Certbot renewal — already wired

`cloud-init.yml` writes renewal hooks for the container-nginx setup:

- `/etc/letsencrypt/renewal-hooks/pre/10-stop-nginx.sh` runs `docker stop ft_nginx || true` so standalone certbot can bind port 80.
- `/etc/letsencrypt/renewal-hooks/post/10-start-nginx.sh` runs `docker start ft_nginx || true` so the proxy comes back after renewal.
- `/etc/letsencrypt/renewal-hooks/deploy/10-reload-nginx.sh` runs `nginx -s reload` **inside the compose nginx container** after every successful renewal.

It also enables `certbot.timer` for the twice-daily renewal check. You don't need to install hooks manually.

Verify after cloud-init:

```bash
systemctl is-enabled certbot.timer       # → enabled
ls /etc/letsencrypt/renewal-hooks/pre    # → 10-stop-nginx.sh
ls /etc/letsencrypt/renewal-hooks/post   # → 10-start-nginx.sh
ls /etc/letsencrypt/renewal-hooks/deploy # → 10-reload-nginx.sh
```

---

## 9. Install systemd units (2 min)

From the repo root on your laptop:

```bash
scp -i ~/.ssh/fasttravel_oracle \
    infra/systemd/*.service \
    infra/systemd/*.timer \
    ubuntu@<public_ip>:/tmp/
```

On the VM:

```bash
sudo mv /tmp/fasttravel-*.service /tmp/fasttravel-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fasttravel-stack.service     # docker-compose at boot
sudo systemctl enable --now fasttravel-snapshot.timer    # 06:00 / 18:00
sudo systemctl enable --now fasttravel-keepalive.timer   # hourly

systemctl list-timers --all | grep fasttravel
```

> **Note**: `fasttravel-stack.service` will exit harmlessly until you deploy a
> full repo checkout plus `.env` to `/opt/fasttravel/` (next step). The prod
> compose file is an overlay and must always be used together with
> `docker-compose.yml`.

---

## 10. Deploy the application

When the application code is ready, `/opt/fasttravel` must be a git checkout.
The GitHub deploy workflow runs `git pull --ff-only origin main` there before
pulling GHCR images.

```bash
# On the VM:
sudo rm -rf /opt/fasttravel
sudo -u fasttravel git clone git@github.com:<owner>/<repo>.git /opt/fasttravel
cd /opt/fasttravel
```

On the VM:

```bash
cd /opt/fasttravel
sudo -u fasttravel ./infra/scripts/secrets-bootstrap.sh .env
sudo -u fasttravel $EDITOR .env   # paste real secrets + GHCR image tags
sudo -u fasttravel ENV_FILE=.env STRICT_ENV=1 ./infra/scripts/production-preflight.sh
sudo systemctl restart fasttravel-stack.service
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

---

## 11. Verify (5 min)

```bash
# From your laptop
curl -fsS https://api.<your-domain>/health   # should return {"status":"ok"} once API is up

# On the VM
sudo journalctl -u fasttravel-stack.service -n 50 --no-pager
sudo journalctl -u fasttravel-snapshot.service -n 50 --no-pager
cd /opt/fasttravel
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100
systemctl list-timers --all | grep fasttravel
```

Open `https://<your-domain>/grafana/` and log in with the basic-auth
credentials you set in step 8. Import the community dashboards:

- **Dashboards → New → Import** → enter `1860` → choose Prometheus → Import.
- Same for `9628`.

The custom `FastTravel — Application` dashboard is loaded automatically via
provisioning.

---

## If reclamation triggers (Oracle "Idle Instance" warning)

Oracle reclaims A1 instances that stay below 20% CPU **and** 20% RAM
**and** 20% network for 7 consecutive days. The hourly keepalive timer is a
best-effort signal — it's not enough on its own to keep you above 20% CPU
(an `INSERT` is ~0% CPU). The combined load from the snapshot job (twice
daily) + APScheduler MV refreshes (hourly) + nginx logs is usually enough,
but if you get a reclamation email:

```bash
# Continuous low-rate pgbench on the VM (~5-10% CPU, well under reclamation):
docker exec -d fasttravel-postgres pgbench -i -s 5 postgres
docker exec -d fasttravel-postgres pgbench -T 0 -c 2 -j 1 -P 60 postgres
```

This generates enough sustained work to stay clearly above the threshold.

---

## Useful diagnostic commands

```bash
# Cloud-init progress / errors
sudo cloud-init status --long
sudo cat /var/log/cloud-init-output.log | less

# Stack health
cd /opt/fasttravel
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker stats --no-stream

# Healthcheck script (runs every minute via crontab)
sudo /usr/local/bin/fasttravel-healthcheck.sh && echo "healthy"

# fail2ban status
sudo fail2ban-client status sshd

# Disk usage
df -h
du -sh /opt/fasttravel /var/lib/docker
```

---

## Disaster recovery

The VM is fully reproducible from this repo:

1. `terraform destroy` (if needed) → `terraform apply` → new VM in ~10 min.
2. Restore Postgres from the latest R2 backup (uploaded daily by GitHub Actions `daily-backup.yml`).
3. Redeploy app code via the steps above.

Total recovery time: ~30 min.
