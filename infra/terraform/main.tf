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
      version = "~> 6.0"
    }
  }

  # Local backend for first apply. Once R2 bucket exists, uncomment the
  # block below and run `terraform init -migrate-state`.
  #
  # backend "s3" {
  #   bucket                      = "fasttravel-tfstate"
  #   key                         = "oracle/terraform.tfstate"
  #   region                      = "auto"
  #   endpoint                    = "https://<account_id>.r2.cloudflarestorage.com"
  #   skip_credentials_validation = true
  #   skip_metadata_api_check     = true
  #   skip_region_validation      = true
  #   force_path_style            = true
  # }
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
