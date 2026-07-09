variable "region" {
  type        = string
  description = "The target Alibaba Cloud region for deployment"
  default     = "cn-hangzhou"
}

variable "dashscope_api_key" {
  type        = string
  description = "The active DashScope Qwen Cloud API Key"
  sensitive   = true
}

variable "target_ecs_ip" {
  type        = string
  description = "The target ECS server node IP address for Logtail mapping"
  default     = "192.168.1.10"
}

variable "custom_domain" {
  type        = string
  description = "Custom CDN domain namespace for static site access"
  default     = "qwen-ops.demo"
}
