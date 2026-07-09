terraform {
  required_providers {
    alicloud = { source = "aliyun/alicloud", version = "~> 1.230" }
  }
}

variable "dashscope_api_key" { type = string, sensitive = true }
variable "region"            { default = "cn-hangzhou" }
variable "target_ecs_ip"     { default = "192.168.1.10" }
variable "custom_domain"     { default = "qwen-ops.demo" }

provider "alicloud" {
  region = var.region
}

# ============================================================
# 1. FUNCTION COMPUTE 3.0 (Orchestrator Runtime)
# ============================================================
resource "alicloud_fc3_function" "autopilot_ops" {
  function_name = "qwen-autopilot-ops"
  runtime       = "python3.10"
  handler       = "src.fc_handler.handler"  # Native FC handler, NOT FastAPI
  memory_size   = 512
  timeout       = 300
  cpu           = 0.35

  environment_variables = {
    DASHSCOPE_API_KEY  = var.dashscope_api_key
    OTS_INSTANCE       = alicloud_ots_instance.state_store.name
    OTS_TABLE          = alicloud_ots_table.incident_state.table_name
    SLS_PROJECT        = alicloud_log_project.ops.name
    SLS_LOGSTORE       = alicloud_log_store.alerts.name
    OSS_BUCKET         = alicloud_oss_bucket.postmortems.bucket
    SAFETY_MODE        = "STRICT"
  }

  code {
    zip_file = base64encode(data.archive_file.source.output_path)
  }
}

# HTTP Trigger for webhook/alert ingestion
resource "alicloud_fc3_trigger" "http" {
  function_name = alicloud_fc3_function.autopilot_ops.function_name
  trigger_name  = "http-trigger"
  trigger_type  = "http"
  trigger_config = jsonencode({
    authType = "anonymous"
    methods  = ["POST", "GET"]
  })
}

# ============================================================
# 2. TABLESTORE (OTS) - Replaces SQLite for State Machine
# ============================================================
resource "alicloud_ots_instance" "state_store" {
  name          = "autopilot-ops-state-${random_id.suffix.hex}"
  description   = "Incident state machine persistence"
  accessed_by   = "Any"
  instance_type = "Performance"
}

resource "alicloud_ots_table" "incident_state" {
  instance_name = alicloud_ots_instance.state_store.name
  table_name    = "incident_sessions"
  primary_key {
    name = "session_id"
    type = "STRING"
  }
  primary_key {
    name = "timestamp"
    type = "INTEGER"
  }
  time_to_live  = 7776000  # 90 days retention
  max_version   = 1
}

# ============================================================
# 3. SLS + LOGTAIL - Agentless Log Collection (No SSH Parsing)
# ============================================================
resource "alicloud_log_project" "ops" { name = "qwen-autopilot-ops-${random_id.suffix.hex}" }

resource "alicloud_log_store" "alerts" {
  project_name = alicloud_log_project.ops.name
  name         = "incident-alerts"
  shard_count  = 2
  ttl          = 30
}

# Logtail config for ECS -> SLS (eliminates SSH log retrieval)
resource "alicloud_log_machine_group" "ecs_group" {
  project_name  = alicloud_log_project.ops.name
  name          = "autopilot-target-ecs"
  identify_type = "ip"
  topic         = "autopilot-ops"
  identify_list = [var.target_ecs_ip]
}

resource "alicloud_logtail_config" "syslog_collection" {
  project_name  = alicloud_log_project.ops.name
  logstore_name = alicloud_log_store.alerts.name
  name          = "syslog-json-parser"

  input_detail = jsonencode({
    filePattern     = "/var/log/messages"
    logPath         = "/var/log"
    logType         = "json_log"
    preserve        = true
    preserveDepth   = 1
    filterRegex     = ["error|fail|oom|killed"]
  })
}

# ============================================================
# 4. OSS + CDN - Cockpit UI Hosting (Not served from FC)
# ============================================================
resource "alicloud_oss_bucket" "cockpit_ui" {
  bucket = "qwen-autopilot-cockpit-${random_id.suffix.hex}"
  acl    = "public-read"
  website {
    index_document = "index.html"
    error_document = "error.html"
  }
}

resource "alicloud_cdn_domain" "cockpit" {
  domain_name = "autopilot-ops.${var.custom_domain}"
  cdn_type    = "web"
  sources {
    content  = alicloud_oss_bucket.cockpit_ui.extranet_endpoint
    type     = "oss"
    priority = 20
  }
}

# ============================================================
# 5. IMMUTABLE POST-MORTEM STORAGE
# ============================================================
resource "alicloud_oss_bucket" "postmortems" {
  bucket = "qwen-autopilot-postmortems-${random_id.suffix.hex}"
  acl    = "private"
  lifecycle_rule {
    id      = "worm-retention"
    enabled = true
    expiration { days = 90 }
  }
}

# Data source for zipping src/ directory
data "archive_file" "source" {
  type        = "zip"
  source_dir  = "${path.module}/../../src"
  output_path = "${path.module}/build/function.zip"
}

resource "random_id" "suffix" { byte_length = 4 }
