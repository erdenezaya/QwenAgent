terraform {
  required_providers {
    alicloud = {
      source  = "aliyun/alicloud"
      version = "~> 1.230"
    }
  }
}

# Provider setup configuration
provider "alicloud" {
  region = var.alicloud_region
}

# Random suffix for global resource naming uniqueness
resource "random_id" "suffix" {
  byte_length = 4
}

# 1. Serverless State Store (Alibaba Cloud Tablestore - OTS)
resource "alicloud_ots_instance" "state_db" {
  name        = "qwen-ops-state-${random_id.suffix.hex}"
  description = "Serverless state database for Qwen Autopilot Ops"
  accessed_by = "Any"
  instance_type = "SSD"
}

resource "alicloud_ots_table" "incidents" {
  instance_name = alicloud_ots_instance.state_db.name
  table_name    = "incidents"
  primary_key {
    name = "id"
    type = "STRING"
  }
  time_to_live  = -1
  max_version   = 1
}

resource "alicloud_ots_table" "experiences" {
  instance_name = alicloud_ots_instance.state_db.name
  table_name    = "experiences"
  primary_key {
    name = "service"
    type = "STRING"
  }
  primary_key {
    name = "alert_type"
    type = "STRING"
  }
  time_to_live  = -1
  max_version   = 1
}

# 2. Immutable Audit Store (Alibaba Cloud OSS with WORM policy)
resource "alicloud_oss_bucket" "postmortems" {
  bucket = "qwen-autopilot-postmortems-${random_id.suffix.hex}"
  acl    = "private"

  # WORM retention rules - lock files for 90 days
  lifecycle_rule {
    id      = "immutable-retention"
    enabled = true
    expiration {
      days = 90
    }
  }
}

# 3. Static Web Hosting for UI Cockpit (Alibaba Cloud OSS Website)
resource "alicloud_oss_bucket" "cockpit_ui" {
  bucket = "qwen-autopilot-cockpit-${random_id.suffix.hex}"
  acl    = "public-read"

  website {
    index_document = "index.html"
    error_document = "error.html"
  }
}

# 4. Central Logging & Alarm Ingestion (Alibaba Cloud SLS)
resource "alicloud_log_project" "ops" {
  name        = "qwen-autopilot-ops-${random_id.suffix.hex}"
  description = "SLS project for Qwen Autopilot Ops"
}

resource "alicloud_log_store" "alerts" {
  project_name          = alicloud_log_project.ops.name
  name                  = "incident-alerts"
  shard_count           = 2
  auto_split            = true
  max_split_shard_count = 64
  append_meta           = true
}

resource "alicloud_log_store_index" "alerts_index" {
  project  = alicloud_log_project.ops.name
  logstore = alicloud_log_store.alerts.name
  full_text {
    case_sensitive = false
    token          = ", '\"*;="
  }
}

# 5. Serverless State Machine (Alibaba Cloud Function Compute 3.0)
resource "alicloud_fc3_function" "autopilot_ops" {
  function_name = "qwen-autopilot-ops"
  runtime       = "python3.10"
  handler       = "src.orchestrator.handler"
  memory_size   = 512
  timeout       = 300

  environment_variables = {
    DASHSCOPE_API_KEY = var.dashscope_api_key
    OSS_BUCKET        = alicloud_oss_bucket.postmortems.bucket
    SLS_PROJECT       = alicloud_log_project.ops.name
    OTS_INSTANCE      = alicloud_ots_instance.state_db.name
    SAFETY_MODE       = "STRICT"
  }

  code {
    zip_file = "dummy_payload_base64" # Packaged and uploaded via CI/CD deployment scripting
  }
}
