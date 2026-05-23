# ----------------------------------------------------------------------------
# Authentication (Identity → Users → API Keys → Add API Key in Oracle Console)
# ----------------------------------------------------------------------------

variable "tenancy_ocid" {
  description = "Tenancy OCID. Found in Profile → Tenancy → OCID."
  type        = string
}

variable "user_ocid" {
  description = "User OCID. Profile → User Settings → OCID."
  type        = string
}

variable "fingerprint" {
  description = "API key fingerprint shown after upload in User Settings → API Keys."
  type        = string
}

variable "private_key_path" {
  description = "Absolute path to the PEM private key paired with the uploaded API public key."
  type        = string
}

variable "region" {
  description = "OCI region. Frankfurt and Amsterdam are popular Always Free regions for Europe."
  type        = string
  default     = "eu-frankfurt-1"
}

variable "compartment_ocid" {
  description = "Compartment to provision into. For a fresh Always Free tenancy this is the tenancy OCID itself."
  type        = string
}

# ----------------------------------------------------------------------------
# Compute / networking
# ----------------------------------------------------------------------------

variable "availability_domain_index" {
  description = "Index into the ADs returned by oci_identity_availability_domains.ads (0/1/2). A1.Flex capacity in EU is scarce — if apply fails with 'Out of host capacity', try the next index."
  type        = number
  default     = 0
}

variable "instance_name" {
  description = "Display name of the VM in the Oracle Console."
  type        = string
  default     = "fasttravel-prod"
}

variable "instance_ocpus" {
  description = "ARM Ampere OCPUs. Always Free quota = 4 across all A1 instances in the tenancy."
  type        = number
  default     = 4
}

variable "instance_memory_gb" {
  description = "RAM in GB. Always Free quota = 24 across all A1 instances."
  type        = number
  default     = 24
}

variable "boot_volume_size_gb" {
  description = "Boot volume size. Always Free block-volume quota = 200 GB total."
  type        = number
  default     = 200
}

variable "ssh_public_key_path" {
  description = "Absolute path to the SSH public key that will be installed into the 'ubuntu' user (and the 'fasttravel' user via cloud-init)."
  type        = string
}

variable "vcn_cidr" {
  description = "CIDR block for the VCN."
  type        = string
  default     = "10.0.0.0/16"
}

variable "subnet_cidr" {
  description = "CIDR block for the public subnet."
  type        = string
  default     = "10.0.1.0/24"
}

variable "ssh_ingress_cidr" {
  description = "CIDR allowed to SSH in. Tighten to your home/office IP for production. 0.0.0.0/0 is acceptable on MVP because fail2ban + key-only auth is configured in cloud-init."
  type        = string
  default     = "0.0.0.0/0"
}
