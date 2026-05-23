# ============================================================================
# Compute: ARM Ampere A1 Flex VM (Always Free shape).
# Image is looked up dynamically in main.tf — never hardcode OCIDs.
# ============================================================================

resource "oci_core_instance" "app" {
  compartment_id      = var.compartment_ocid
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[var.availability_domain_index].name
  display_name        = var.instance_name
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = var.instance_ocpus
    memory_in_gbs = var.instance_memory_gb
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu_22_04_arm.images[0].id
    boot_volume_size_in_gbs = var.boot_volume_size_gb
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.public.id
    assign_public_ip = true # ephemeral IP, replaced by Reserved IP after apply
    hostname_label   = "app"
  }

  metadata = {
    ssh_authorized_keys = file(var.ssh_public_key_path)
    user_data           = base64encode(file("${path.module}/../cloud-init.yml"))
  }

  # Boot volume sizing is part of the free tier (≤200 GB total)
  preserve_boot_volume = false

  lifecycle {
    ignore_changes = [
      # cloud-init updates aren't re-applied without recreating the VM;
      # avoid unintended replacement on every `terraform plan`.
      metadata["user_data"],
      source_details[0].source_id,
    ]
  }
}

# ----------------------------------------------------------------------------
# Lookup chain to find the instance's primary private IP OCID. The Reserved
# Public IP in networking.tf attaches to this private IP, not the instance.
# ----------------------------------------------------------------------------

data "oci_core_vnic_attachments" "instance" {
  compartment_id = var.compartment_ocid
  instance_id    = oci_core_instance.app.id
}

data "oci_core_vnic" "primary" {
  vnic_id = data.oci_core_vnic_attachments.instance.vnic_attachments[0].vnic_id
}

data "oci_core_private_ips" "instance" {
  vnic_id = data.oci_core_vnic.primary.id
}
