# ============================================================================
# FastTravel — Oracle Cloud Always Free infrastructure
# ----------------------------------------------------------------------------
# Provisions:
#   * VCN + public subnet + Internet Gateway + security list (22/80/443)
#   * VM.Standard.A1.Flex (4 OCPU / 24 GB / 200 GB) on Ubuntu 22.04 ARM
#   * Reserved Public IP (free tier: 2 per tenancy)
#   * cloud-init bootstrap (../cloud-init.yml)
#
# Backend: local state on first apply. Migration to S3-compatible
# (Cloudflare R2) is documented in README.md — Phase 2.
# ============================================================================

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 8.15"
    }
  }

  # Audit Quarter #19 — remote state on Cloudflare R2.
  # The previous comment-only block left local-only state ("bus factor = 1").
  # R2's S3-compatible API works with Terraform's `s3` backend; we lose
  # native locking (DynamoDB is AWS-only), but adding `use_lockfile = true`
  # (Terraform 1.10+) provides best-effort S3-side lock files.
  #
  # Operator one-time setup:
  #   1. Create an R2 bucket `fasttravel-tfstate` (private, no public list).
  #   2. Mint an R2 token with Read/Write on that bucket.
  #   3. Export the credentials before `terraform init`:
  #         export AWS_ACCESS_KEY_ID=<r2 token id>
  #         export AWS_SECRET_ACCESS_KEY=<r2 token secret>
  #   4. Set var.r2_account_id and var.r2_state_bucket in terraform.tfvars,
  #      then `terraform init -migrate-state`.
  #
  # Until configured, the backend stays local so first-apply on a fresh
  # checkout still works.
  backend "s3" {
    # Required values are filled in via `terraform init -backend-config`:
    #   terraform init -migrate-state \
    #     -backend-config="bucket=fasttravel-tfstate" \
    #     -backend-config="key=oracle/terraform.tfstate" \
    #     -backend-config="endpoints={s3=\"https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com\"}"
    # When the env vars aren't set, init prompts interactively.
    region                      = "auto"
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true
    use_path_style              = true
    # Best-effort lock via S3-side state file (Terraform 1.10+).
    use_lockfile = true
  }
}

provider "oci" {
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.private_key_path
  region           = var.region
}

# ----------------------------------------------------------------------------
# Lookups (no hardcoded OCIDs — they go stale)
# ----------------------------------------------------------------------------

data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

# Most recent Canonical Ubuntu 22.04 aarch64 image in the chosen region.
data "oci_core_images" "ubuntu_22_04_arm" {
  compartment_id           = var.tenancy_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "22.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"

  # Filter out minimal/GPU variants — we want the standard server image
  # whose display_name contains "aarch64".
  filter {
    name   = "display_name"
    values = [".*aarch64.*"]
    regex  = true
  }
}
