variable "alicloud_region" {
  type        = string
  description = "The target Alibaba Cloud region for deployment"
  default     = "cn-hangzhou"
}

variable "dashscope_api_key" {
  type        = string
  description = "The active DashScope Qwen Cloud API Key"
  sensitive   = true
}
