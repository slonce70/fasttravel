output "public_ip" {
  description = "Reserved Public IP to whitelist with ittour and to A-record in Cloudflare DNS."
  value       = oci_core_public_ip.reserved.ip_address
}

output "instance_id" {
  description = "OCID of the VM (useful for `oci compute instance` CLI calls)."
  value       = oci_core_instance.app.id
}

output "instance_state" {
  description = "Current lifecycle state — should be RUNNING once apply completes."
  value       = oci_core_instance.app.state
}

output "ssh_command" {
  description = "Convenience command to SSH in once cloud-init finishes (~5 min after apply)."
  value       = "ssh -i ${replace(var.ssh_public_key_path, ".pub", "")} ubuntu@${oci_core_public_ip.reserved.ip_address}"
}

output "ubuntu_image_id" {
  description = "Resolved Ubuntu 22.04 ARM image OCID at apply time (for audit)."
  value       = data.oci_core_images.ubuntu_22_04_arm.images[0].id
}

output "availability_domain" {
  description = "AD used. If apply failed with capacity errors, try a different availability_domain_index in tfvars."
  value       = data.oci_identity_availability_domains.ads.availability_domains[var.availability_domain_index].name
}
