import os
import json
import uuid
import time
from openai import OpenAI
from backend import memory
from backend import tools

# Load local .env file if it exists in the root directory
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(env_path):
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
BASE_URL = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")

# Models aliases on DashScope
TRIAGE_MODEL = "qwen-plus"
REMEDIATION_MODEL = "qwen-max"
VERIFY_MODEL = "qwen-plus"

def get_qwen_client():
    """Initializes and returns the OpenAI client configured for DashScope Qwen Cloud."""
    if not API_KEY:
        return None
    return OpenAI(api_key=API_KEY, base_url=BASE_URL)

def run_triage_agent(incident_id: str, raw_alert: str) -> dict:
    """
    Triage Agent (Qwen-Plus):
    Parses the raw unstructured alert, fetches logs from tools, extracts key entities,
    categorizes severity, and performs a Root Cause Analysis (RCA).
    """
    client = get_qwen_client()
    
    # Pre-parse service/host using simple heuristic to fetch logs before Qwen call
    alert_lower = raw_alert.lower()
    guessed_service = "unknown"
    if "tomcat" in alert_lower: guessed_service = "tomcat"
    elif "mysql" in alert_lower or "database" in alert_lower: guessed_service = "mysql"
    elif "nginx" in alert_lower: guessed_service = "nginx"
    elif "disk" in alert_lower or "storage" in alert_lower or "space" in alert_lower: guessed_service = "disk-storage"
    
    guessed_host = "sys-node-04"
    if "web" in alert_lower: guessed_host = "web-prod-01"
    elif "db" in alert_lower or "mysql" in alert_lower: guessed_host = "db-prod-02"
    elif "srv" in alert_lower: guessed_host = "srv-app-09"
    
    # Fetch diagnostic logs
    log_result = tools.fetch_service_logs(guessed_service, guessed_host)
    service_logs = log_result.get("log_content", "No logs fetched.")
    
    system_prompt = (
        "You are the Triage and Diagnostic Agent in an automated IT operations center. "
        "Your task is to parse unstructured alert messages, analyze service logs, "
        "extract key entities, and perform a Root Cause Analysis (RCA).\n\n"
        "Identify:\n"
        "1. Affected Service (e.g. tomcat, mysql, nginx, disk-storage)\n"
        "2. Hostname/Server name (e.g. web-prod-01)\n"
        "3. Severity Level (low, medium, high, critical)\n"
        "4. Brief Triage Reasoning explanation.\n"
        "5. Root Cause Analysis (RCA): Explain exactly why this failure occurred based on the logs provided.\n\n"
        "Output ONLY a valid JSON object matching this schema:\n"
        "{\n"
        '  "service": "service_name",\n'
        '  "host": "hostname",\n'
        '  "severity": "severity_level",\n'
        '  "triage_reasoning": "your detailed reasoning explanation",\n'
        '  "root_cause": "detailed root cause diagnostic summary"\n'
        "}\n"
        "Do not include any markdown block formatting (like ```json) in your final output, just raw JSON."
    )
    
    # If API_KEY is missing, run in high-fidelity mock mode
    if not client:
        time.sleep(1.5) # Simulate network lag
        
        severity = "medium"
        if any(w in alert_lower for w in ["98%", "full", "unresponsive", "failed", "critical"]):
            severity = "critical" if "mysql" in guessed_service else "high"
        elif "warning" in alert_lower:
            severity = "low"
            
        reasoning = (
            f"Detected service '{guessed_service}' reporting issues on host '{guessed_host}'. "
            f"Based on raw keywords, categorized severity as '{severity}' and flagged for immediate resolution evaluation."
        )
        
        root_cause = "Unknown root cause."
        if guessed_service == "tomcat":
            root_cause = "JVM Heap Space OOM (OutOfMemoryError) triggered by stuck worker threads in Catalina pool on port 8080."
        elif guessed_service == "mysql":
            root_cause = "MySQL daemon crashed because InnoDB table flags are corrupt, causing a PID lock and too many open files."
        elif guessed_service == "nginx":
            root_cause = "Nginx critical write error: Upstream timed out because writing temporary proxy files failed due to disk space exhausted (No space left on device)."
        elif guessed_service == "disk-storage":
            root_cause = "Log volume capacity exceeded. /var/log accesses logs and journald traces have filled up 99.8% of local disk."
            
        parsed = {
            "service": guessed_service,
            "host": guessed_host,
            "severity": severity,
            "triage_reasoning": reasoning,
            "root_cause": root_cause
        }
    else:
        try:
            response = client.chat.completions.create(
                model=TRIAGE_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Alert: {raw_alert}\n\nFetched Logs:\n{service_logs}"}
                ],
                temperature=0.1
            )
            content = response.choices[0].message.content.strip()
            # Clean up potential markdown formatting
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            parsed = json.loads(content)
        except Exception as e:
            # Graceful fallback on API error
            parsed = {
                "service": "tomcat",
                "host": "web-prod-01",
                "severity": "high",
                "triage_reasoning": f"Qwen API query failed ({str(e)}). Used default fallback parameters."
            }

    # Update incident in database
    parsed["id"] = incident_id
    parsed["status"] = "triage_completed"
    memory.save_incident(parsed)
    return parsed

def run_remediation_agent(incident_id: str) -> dict:
    """
    Remediation Agent (Qwen-Max):
    1. Queries SQLite persistent memory for similar historical incidents.
    2. Uses experience logs to choose the correct tool.
    3. Decides if human approval is required based on severity/impact.
    4. Outputs tool name, arguments, and reasoning.
    """
    incident = memory.get_incident(incident_id)
    if not incident:
        return {"error": "Incident not found"}
        
    service = incident.get("service", "unknown")
    host = incident.get("host", "unknown")
    severity = incident.get("severity", "medium")
    
    # Retrieve past memories
    relevant_memories = memory.get_relevant_memories(service, incident.get("raw_alert", ""))
    memory_context = ""
    if relevant_memories:
        memory_context = "Historical experience found in persistent memory:\n"
        for mem in relevant_memories[:3]:
            outcome = "SUCCESSFUL" if mem["success"] == 1 else "FAILED"
            memory_context += (
                f"- Action: '{mem['action_taken']}' for '{mem['service']}' ({mem['alert_type']}) "
                f"was {outcome} (Run count: {mem['run_count']})\n"
            )
    else:
        memory_context = "No previous history found in persistent memory for this type of alert.\n"

    system_prompt = (
        "You are the Remediation Agent. Your job is to analyze the parsed incident, recall past memories, "
        "select the best system administration tool, and formulate an action plan.\n\n"
        f"Incident details:\n"
        f"- Service: {service}\n"
        f"- Host: {host}\n"
        f"- Severity: {severity}\n\n"
        f"{memory_context}\n"
        "Available Tools:\n"
        "1. restart_service(service_name, host): Use for service downtime, crashes, or high load.\n"
        "2. clear_disk_space(path, host, file_pattern): Use for disk full, logs buildup. Safe paths: '/var/log', '/tmp'.\n"
        "3. scale_kubernetes_deployment(deployment_name, namespace, replicas): Use for high application load/pod crashes.\n\n"
        "Approval Policy:\n"
        "- Destructive actions or restarts on 'prod' hosts or critical severities (high/critical) REQUIRE human approval.\n"
        "- Cleanups or low-severity actions do NOT require human approval (auto-approve).\n\n"
        "Respond ONLY with a valid JSON block containing the fields:\n"
        "{\n"
        '  "tool_name": "name_of_selected_tool",\n'
        '  "tool_arguments": {"arg1": "val1"},\n'
        '  "requires_approval": true/false,\n'
        '  "remediation_plan": "Step-by-step description of what you plan to do, citing historical memories if applicable."\n'
        "}\n"
        "Do not output markdown code blocks (like ```json), just raw JSON."
    )

    client = get_qwen_client()
    
    if not client:
        time.sleep(2.0) # Simulate network lag
        # Mock smart reasoning based on service and severity
        requires_approval = severity in ["high", "critical"] or "prod" in host.lower()
        
        if service == "tomcat":
            tool_name = "restart_service"
            tool_args = {"service_name": "tomcat", "host": host}
            plan = "Detected Tomcat JVM resource leak or crash. Recalled historical memory showing restart_service has a 100% success rate. Initiating Tomcat service reboot."
        elif service == "mysql":
            tool_name = "restart_service"
            tool_args = {"service_name": "mysql", "host": host}
            plan = "Database connection timed out. Persistent memory records show restart_service is the primary recovery pathway. Restarts on database tier require human review to prevent transaction interrupts."
            requires_approval = True # Always require DB approval
        elif service == "nginx":
            tool_name = "restart_service"
            tool_args = {"service_name": "nginx", "host": host}
            plan = "Web proxy service Nginx sluggish or down. Initiating restart action."
        elif service == "disk-storage":
            tool_name = "clear_disk_space"
            # Parse path if mentioned, else default
            tool_args = {"path": "/var/log", "host": host, "file_pattern": "*.log"}
            plan = "Server volume full. Historical experiences dictate that clearing syslogs or access log archives resolves the storage issue without data loss. Auto-approving disk cleanup."
            requires_approval = False # Safe disk cleanups are auto-approved
        else:
            tool_name = "restart_service"
            tool_args = {"service_name": service, "host": host}
            plan = f"Unknown issue for service {service}. Defaulting to service restart policy."
            
        parsed = {
            "tool_name": tool_name,
            "tool_arguments": tool_args,
            "requires_approval": requires_approval,
            "remediation_plan": plan
        }
    else:
        try:
            response = client.chat.completions.create(
                model=REMEDIATION_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Formulate remediation for Incident ID: {incident_id}"}
                ],
                temperature=0.1
            )
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            parsed = json.loads(content)
        except Exception as e:
            parsed = {
                "tool_name": "restart_service",
                "tool_arguments": {"service_name": service, "host": host},
                "requires_approval": True,
                "remediation_plan": f"API error ({str(e)}). Defaulted to restart tool with human approval required."
            }
            
    # Update incident in db
    update_data = {
        "id": incident_id,
        "remediation_plan": parsed["remediation_plan"],
        "requires_approval": parsed["requires_approval"],
        "status": "pending_approval" if parsed["requires_approval"] else "approved"
    }
    
    # Save selection details inside the plan or log columns for frontend retrieval
    # Store tool details inside the execution_logs or a serialized structure
    tool_meta = {
        "name": parsed["tool_name"],
        "args": parsed["tool_arguments"]
    }
    update_data["execution_logs"] = json.dumps({"planned_tool": tool_meta, "runs": []})
    
    memory.save_incident(update_data)
    return parsed

def execute_remediation(incident_id: str, approved_by: str = None) -> dict:
    """Runs the selected tool, collects execution logs, and transitions status."""
    incident = memory.get_incident(incident_id)
    if not incident:
        return {"error": "Incident not found"}
        
    logs_data = json.loads(incident["execution_logs"])
    tool_meta = logs_data["planned_tool"]
    
    # Update status to executing
    memory.save_incident({
        "id": incident_id,
        "status": "executing",
        "approved_by": approved_by
    })
    
    # Run the tool
    tool_result = tools.execute_tool(tool_meta["name"], tool_meta["args"])
    
    # Save logs and update status
    run_log = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tool": tool_meta["name"],
        "args": tool_meta["args"],
        "success": tool_result["success"],
        "output": tool_result["message"],
        "details": tool_result["logs"]
    }
    logs_data["runs"].append(run_log)
    
    new_status = "executing_completed" if tool_result["success"] else "failed"
    
    memory.save_incident({
        "id": incident_id,
        "status": new_status,
        "execution_logs": json.dumps(logs_data)
    })
    
    return tool_result

def run_verification_agent(incident_id: str) -> dict:
    """
    Verification Agent (Qwen-Plus/Turbo):
    1. Invokes check_service_health for the affected service/host.
    2. Uses Qwen to analyze health metrics and logs.
    3. Confirms if incident is resolved or needs further loops.
    4. Updates database memory based on result.
    """
    incident = memory.get_incident(incident_id)
    if not incident:
        return {"error": "Incident not found"}
        
    service = incident.get("service")
    host = incident.get("host")
    
    # Check health tool invocation
    health_result = tools.check_service_health(service, host)
    
    system_prompt = (
        "You are the Verification Agent. Your job is to check the health diagnostics of the service "
        "after remediation and decide if the incident is completely resolved.\n\n"
        f"Service: {service}\n"
        f"Host: {host}\n"
        f"Remediation plan executed: {incident.get('remediation_plan')}\n\n"
        f"Health Diagnostics logs:\n{health_result['logs']}\n\n"
        "Respond ONLY with a valid JSON matching this schema:\n"
        "{\n"
        '  "resolved": true/false,\n'
        '  "verification_details": "Explain why it is resolved or what is still failing based on metrics.",\n'
        '  "resolution_summary": "Provide a 1-sentence action summary of how the issue was resolved (e.g. Restarted MySQL on db-prod-02, clearing InnoDB lock flags)."\n'
        "}\n"
        "Do not include markdown tags."
    )
    
    client = get_qwen_client()
    
    if not client:
        time.sleep(1.5)
        # Mock verification
        resolved = health_result["success"]
        details = (
            f"Verified service '{service}' status on '{host}'. The TCP port check succeeded, "
            f"and metrics show stable CPU load ({health_result['metrics']['cpu_percent']}%) "
            f"and memory allocation ({health_result['metrics']['memory_mb']}MB). Issue resolved."
        )
        resolution_summary = "Remediation executed successfully."
        if service == "tomcat":
            resolution_summary = f"Restarted Tomcat service on host {host}, clearing JVM heap space leakage."
        elif service == "mysql":
            resolution_summary = f"Approved and executed MySQL service reboot on host {host}, recovering active database port 3306."
        elif service == "nginx":
            resolution_summary = f"Restarted Nginx proxy on host {host} to establish configuration settings."
        elif service == "disk-storage":
            resolution_summary = f"Cleared access log archives under '/var/log' on host {host}, freeing up disk space."
            
        parsed = {
            "resolved": resolved,
            "verification_details": details,
            "resolution_summary": resolution_summary
        }
    else:
        try:
            response = client.chat.completions.create(
                model=VERIFY_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Verify Incident ID: {incident_id}"}
                ],
                temperature=0.1
            )
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            parsed = json.loads(content)
        except Exception as e:
            parsed = {
                "resolved": health_result["success"],
                "verification_details": f"Verification parsed via fallback due to API error: {str(e)}",
                "resolution_summary": "Executed remediation successfully."
            }
            
    # Update incident in db
    new_status = "resolved" if parsed["resolved"] else "failed"
    logs_data = json.loads(incident["execution_logs"])
    tool_meta = logs_data["planned_tool"]
    memory.save_incident({
        "id": incident_id,
        "status": new_status,
        "verification_results": parsed["verification_details"],
        "resolution_summary": parsed.get("resolution_summary", f"Successfully executed tool {tool_meta['name']}")
    })
    
    # Store this outcome in persistent cognitive memory
    logs_data = json.loads(incident["execution_logs"])
    tool_meta = logs_data["planned_tool"]
    action_str = f"Run tool: {tool_meta['name']} with {json.dumps(tool_meta['args'])}"
    
    memory.record_experience(
        service=service,
        alert_type=incident["raw_alert"][:100], # Keep a snippet
        action_taken=action_str,
        success=parsed["resolved"]
    )
    
    return parsed

def process_alert_full_flow(raw_alert: str) -> str:
    """Utility function to run the full flow for alerts that don't need approvals."""
    incident_id = str(uuid.uuid4())[:8]
    memory.save_incident({
        "id": incident_id,
        "raw_alert": raw_alert,
        "status": "received"
    })
    
    # 1. Triage
    run_triage_agent(incident_id, raw_alert)
    
    # 2. Remediation selection
    remed = run_remediation_agent(incident_id)
    
    # 3. If auto-approved, execute right away
    if not remed["requires_approval"]:
        execute_remediation(incident_id, approved_by="system-autopilot")
        run_verification_agent(incident_id)
        
    return incident_id
