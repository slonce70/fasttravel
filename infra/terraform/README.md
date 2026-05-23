# FastTravel — Terraform for Oracle Cloud Always Free

Infrastructure as code for the production VM. Always Free, $0/month.

What this provisions:

- **VCN** + public subnet + Internet Gateway + security list (22/80/443/icmp).
- **VM.Standard.A1.Flex** — 4 OCPU, 24 GB RAM, 200 GB boot volume, Ubuntu 22.04 ARM.
- **Reserved Public IP** (free tier allows 2 per tenancy) — required for `ittour` API IP-bind.
- The VM bootstraps itself via [`../cloud-init.yml`](../cloud-init.yml).

## Prerequisites (one-time, ~20 min)

1. **Oracle Cloud account.** Sign up at <https://signup.cloud.oracle.com/>. Pick a home region that supports Always Free (Frankfurt, Amsterdam, London are good for EU; pick whichever your card billing allows). The home region cannot be changed later.
2. **Install Terraform** ≥ 1.6 — `brew install terraform` on macOS.
3. **Install the OCI CLI** (optional but helpful for debugging) — `brew install oci-cli`.
4. **Generate an API key pair** for Terraform:

   ```bash
   mkdir -p ~/.oci
   openssl genrsa -out ~/.oci/fasttravel_api_key.pem 2048
   chmod 600  ~/.oci/fasttravel_api_key.pem
   openssl rsa -pubout -in  ~/.oci/fasttravel_api_key.pem \
                       -out ~/.oci/fasttravel_api_key_public.pem
   ```

5. **Upload the public key** to OCI: top-right avatar → **User Settings** → **Resources → API Keys** → **Add API Key** → paste the contents of `fasttravel_api_key_public.pem`. After upload, copy the **Fingerprint** that appears.
6. **Generate an SSH key pair** for accessing the VM:

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/fasttravel_oracle -C "fasttravel-prod"
   ```

7. **Grab OCIDs:**
   - Tenancy OCID — top-right avatar → **Tenancy: <name>** → **OCID** (copy).
   - User OCID — top-right avatar → **User Settings** → **OCID** (copy).
   - Compartment OCID — for a brand-new tenancy with no sub-compartments, **use the tenancy OCID**. Sub-compartments come later if you split prod/dev.

## Apply

```bash
cd infra/terraform
cp example.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars   # paste the OCIDs, fingerprint, paths

terraform init
terraform plan -out=plan.out
terraform apply plan.out
```

Expect ~2 min for the VM to be created and reach `RUNNING`, then ~5 min for `cloud-init` to finish installing Docker / nginx / certbot / fail2ban / ufw.

Outputs include:

- `public_ip` — the Reserved IP. Point your A-record to it and pass it to ittour.
- `ssh_command` — copy-pasteable `ssh` for first login.

## "Out of host capacity" — what to do

A1.Flex capacity in EU regions is famously over-subscribed. If `apply` returns `InternalError ... Out of host capacity`:

1. Re-run `terraform apply` — capacity frees up every few minutes.
2. Bump `availability_domain_index` from `0` → `1` → `2` in `terraform.tfvars` and re-apply.
3. If nothing works for a day, switch `region` to `uk-london-1` or `me-jeddah-1` (you'll have to recreate the tenancy if you started elsewhere — region is sticky).

A community trick: a small `while`-loop running `terraform apply` every 60 s often catches a free slot within an hour. Don't hammer faster — Oracle rate-limits.

## State backend

Default: **local state** (`terraform.tfstate` in this directory). Acceptable while you're the only operator.

**Phase 2 — migrate to Cloudflare R2** (S3-compatible, 10 GB free, $0 egress):

1. Create R2 bucket `fasttravel-tfstate` in the Cloudflare dashboard.
2. Create an R2 API token with read+write on the bucket. Note the Access Key ID, Secret, and account ID.
3. Uncomment the `backend "s3"` block in [`main.tf`](./main.tf) and fill in `endpoint`.
4. Export creds:

   ```bash
   export AWS_ACCESS_KEY_ID=<r2_access_key_id>
   export AWS_SECRET_ACCESS_KEY=<r2_secret>
   ```

5. `terraform init -migrate-state` — Terraform copies the local state to R2 and locks it.

## Quotas worth knowing

| Resource | Always Free quota | Used here |
|---|---|---|
| A1.Flex OCPUs | 4 per tenancy | 4 |
| A1.Flex memory | 24 GB per tenancy | 24 GB |
| Block volume | 200 GB total | 200 GB (boot) |
| Reserved Public IPs | 2 | 1 |
| VCNs | "no enforced limit" but soft cap ~3 | 1 |
| Egress | 10 TB/month | far below |

The 200 GB boot volume **exhausts the free block-volume quota** — you cannot attach additional volumes without paying. If you outgrow it, the migration path in [`docs/DECISIONS.md`](../../docs/DECISIONS.md) is a Hetzner CX22 read-replica.

## Files

| File | Purpose |
|---|---|
| `main.tf` | Provider config, image/AD data sources |
| `variables.tf` | Input variables |
| `networking.tf` | VCN, subnet, IGW, route table, security list, Reserved IP |
| `compute.tf` | VM + VNIC lookup chain |
| `outputs.tf` | `public_ip`, `instance_id`, `ssh_command`, etc. |
| `example.tfvars.example` | Copy → `terraform.tfvars` and fill in |
| `.gitignore` | Excludes `*.tfstate`, `*.tfvars`, `.terraform/` |

## Destroy

```bash
terraform destroy
```

This kills the VM and releases the Reserved IP. Boot volume is deleted because `preserve_boot_volume = false`. Make sure you've backed up Postgres to R2 first (see GitHub Actions `daily-backup.yml`).
