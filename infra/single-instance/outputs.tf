output "public_ip" {
  description = "Point the domain's A record here (unless Route 53 is managed by this stack)."
  value       = aws_eip.app.public_ip
}

output "site_url" {
  value = "https://${var.domain}"
}

output "instance_id" {
  value = aws_instance.app.id
}

output "session_command" {
  description = "Open a shell on the instance without SSH."
  value       = "aws ssm start-session --target ${aws_instance.app.id} --region ${var.region}"
}

output "audio_bucket" {
  value = aws_s3_bucket.audio.bucket
}

output "releases_bucket" {
  description = "CI uploads release tarballs here; the instance pulls them with its role."
  value       = aws_s3_bucket.releases.bucket
}

output "kms_key_alias" {
  description = "Use this as --key-id when creating the SecureString parameters."
  value       = aws_kms_alias.app.name
}

output "ssm_parameter_path" {
  description = "Create the secret parameters under this path (see docs/runbooks/deploy-single-instance.md)."
  value       = local.ssm_path
}
