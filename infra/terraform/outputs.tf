output "tablestore_instance" {
  value       = alicloud_ots_instance.state_db.name
  description = "The generated serverless OTS instance name"
}

output "postmortem_oss_bucket" {
  value       = alicloud_oss_bucket.postmortems.bucket
  description = "The generated private postmortem audit OSS bucket name"
}

output "cockpit_ui_url" {
  value       = "http://${alicloud_oss_bucket.cockpit_ui.bucket}.oss-${var.alicloud_region}.aliyuncs.com/index.html"
  description = "The static cockpit web UI URL hosted on OSS"
}

output "sls_project" {
  value       = alicloud_log_project.ops.name
  description = "The Simple Log Service project name"
}
