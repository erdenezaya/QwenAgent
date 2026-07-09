import os
import json
from pathlib import Path
from openai import OpenAI

# Load credentials
API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
BASE_URL = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")

# Default Prompts fallback configuration
DEFAULT_PROMPTS = {
    "diagnose_system": (
        "You are the Triage and Diagnostic Agent. Your task is to parse alert logs, identify host/service names, and output a root cause analysis (RCA).\n"
        "Identify:\n"
        "1. Affected Service (e.g., tomcat, mysql, nginx, disk-storage)\n"
        "2. Hostname/Server name (e.g., web-prod-01)\n"
        "3. Severity Level (low, medium, high, critical)\n"
        "4. Root Cause Analysis summary explaining why the log exception was triggered.\n"
        "Output ONLY a JSON block with keys: \"service\", \"host\", \"severity\", \"triage_reasoning\", and \"root_cause\". Do not wrap in markdown tags."
    ),
    "plan_system": (
        "You are the Remediation Planner Agent. Select the optimal command pattern from the allowlist to solve the diagnosed root cause.\n"
        "Allowed patterns:\n"
        "- systemctl restart {service}\n"
        "- find {path} -name '*.log' -mtime +{days} -delete\n"
        "- logrotate -f /etc/logrotate.d/{config}\n"
        "Output ONLY a JSON block with keys: \"command\" and \"id\" (random string). Do not wrap in markdown tags."
    )
}

def load_prompts():
    """Loads system prompts from config yaml file if available."""
    config_path = Path(__file__).parent / "config" / "prompts.yaml"
    if config_path.exists():
        try:
            import yaml
            return yaml.safe_load(config_path.read_text())
        except Exception:
            # Fallback manual text parser to bypass PyYAML missing dependency in basic runtimes
            try:
                content = config_path.read_text()
                prompts = {}
                current_key = None
                current_val = []
                for line in content.splitlines():
                    if line.endswith(": >") or line.endswith(":"):
                        if current_key:
                            prompts[current_key] = "\n".join(current_val).strip()
                        current_key = line.split(":")[0].strip()
                        current_val = []
                    elif current_key and line.strip():
                        current_val.append(line.strip())
                if current_key:
                    prompts[current_key] = "\n".join(current_val).strip()
                return prompts
            except Exception:
                pass
    return DEFAULT_PROMPTS

PROMPTS = load_prompts()

class QwenRouter:
    @staticmethod
    def get_client():
        if not API_KEY or "sk-ws-H.YXRXEY" in API_KEY or "****" in API_KEY:
            # Detect simulated developer api keys
            return None
        return OpenAI(api_key=API_KEY, base_url=BASE_URL)

    @staticmethod
    async def diagnose(session: dict) -> dict:
        """Complex root cause analysis routed to qwen-max"""
        client = QwenRouter.get_client()
        alert = session.get("alert", {})
        logs = session.get("logs", "")
        
        if not client:
            alert_text = alert.get("alert_text", "").lower()
            service = "tomcat" if "tomcat" in alert_text else "mysql" if "mysql" in alert_text else "nginx" if "nginx" in alert_text else "disk-storage"
            host = "db-prod-02" if "db" in alert_text else "srv-app-09" if "srv" in alert_text else "web-prod-01"
            
            rca = "Log capacity threshold exceeded."
            if service == "tomcat":
                rca = "Catalina servlet container triggered OutOfMemoryError in Java heap space."
            elif service == "mysql":
                rca = "MySQL daemon crashed because InnoDB ibdata1 tablespace file is locked."
                
            return {
                "service": service,
                "host": host,
                "severity": "critical" if "critical" in alert_text or "fail" in alert_text else "medium",
                "triage_reasoning": "Mock diagnosis completed locally.",
                "root_cause": rca
            }

        response = client.chat.completions.create(
            model="qwen-max",
            messages=[
                {"role": "system", "content": PROMPTS.get("diagnose_system", DEFAULT_PROMPTS["diagnose_system"])},
                {"role": "user", "content": json.dumps({"alert": alert, "logs": logs})}
            ],
            temperature=0.1
        )
        content = response.choices[0].message.content.strip()
        # Clean markdown code blocks if generated
        if content.startswith("```"):
            content = content.split("```", 2)[1]
            if content.startswith("json"):
                content = content[4:]
        return json.loads(content.strip())

    @staticmethod
    async def plan_remediation(session: dict) -> dict:
        """Structured tool selection routed to qwen-plus"""
        client = QwenRouter.get_client()
        diagnosis = session.get("diagnosis", {})
        
        if not client:
            service = diagnosis.get("service", "disk-storage")
            if service == "tomcat":
                cmd = "systemctl restart tomcat"
            elif service == "mysql":
                cmd = "systemctl restart mysql"
            elif service == "nginx":
                cmd = "systemctl restart nginx"
            else:
                cmd = "find /var/log -name '*.log' -mtime +7 -delete"
            return {
                "command": cmd,
                "id": "remediation-mock-id"
            }

        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": PROMPTS.get("plan_system", DEFAULT_PROMPTS["plan_system"])},
                {"role": "user", "content": json.dumps(diagnosis)}
            ],
            temperature=0.1
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```", 2)[1]
            if content.startswith("json"):
                content = content[4:]
        return json.loads(content.strip())
