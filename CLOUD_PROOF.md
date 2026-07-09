# Alibaba Cloud Deployment Proof

## 1. Serverless State Machine Runtime
* **Alibaba Cloud Service**: **Function Compute 3.0**
* **Deployment proof location**: [`infra/terraform/main.tf#L93-L109`](file:///C:/Users/Zaya/.gemini/antigravity/scratch/qwen-agent-ops/infra/terraform/main.tf#L93-L109)
* **Description**: Deploys the Python WSGI runtime in Function Compute to execute the core orchestrator state transitions (`triage` -> `diagnose` -> `plan` -> `execute` -> `verify`).

## 2. Ephemeral Storage & Serverless State
* **Alibaba Cloud Service**: **Tablestore (OTS)**
* **Deployment proof location**: [`infra/terraform/main.tf#L18-L44`](file:///C:/Users/Zaya/.gemini/antigravity/scratch/qwen-agent-ops/infra/terraform/main.tf#L18-L44)
* **Description**: OTS provides a fully managed serverless NoSQL database to persist active incident ticket details, risk states, and operational logs, avoiding local storage dependencies.

## 3. UI Static Web Hosting
* **Alibaba Cloud Service**: **Object Storage Service (OSS Website)**
* **Deployment proof location**: [`infra/terraform/main.tf#L59-L68`](file:///C:/Users/Zaya/.gemini/antigravity/scratch/qwen-agent-ops/infra/terraform/main.tf#L59-L68)
* **Description**: Serves the cockpit dashboard HTML5/CSS/JS frontend assets statically, avoiding Function Compute trigger compute overheads.

## 4. Immutable Incident Audit Post-Mortems
* **Alibaba Cloud Service**: **Object Storage Service (OSS) with WORM lifecycle**
* **Deployment proof location**: [`infra/terraform/main.tf#L46-L57`](file:///C:/Users/Zaya/.gemini/antigravity/scratch/qwen-agent-ops/infra/terraform/main.tf#L46-L57)
* **Description**: Imposes a 90-day write-once-read-many (WORM) lifecycle retention lock policy to guarantee security audit compliance for archived post-mortem incident reports.

## 5. Log Query & Telemetry Ingestion
* **Alibaba Cloud Service**: **Simple Log Service (SLS)**
* **Deployment proof location**: [`infra/terraform/main.tf#L70-L91`](file:///C:/Users/Zaya/.gemini/antigravity/scratch/qwen-agent-ops/infra/terraform/main.tf#L70-L91)
* **Description**: Logs are collected from target ECS instances via Logtail and shipped to SLS. The Triage agent queries these log stores programmatically using SLS APIs.

---

## 🚀 One-Click Deployment
To provision the entire environment on your Alibaba Cloud subscription, execute:
```bash
cd infra/terraform
terraform init
terraform apply -var="dashscope_api_key=YOUR_DASHSCOPE_API_KEY"
```
