import os
import uuid
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List

from backend import memory
from backend import agent
from backend import alibaba_cloud_proof

app = FastAPI(title="Qwen Autopilot Ops API", version="1.0.0")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic schemas
class AlertInput(BaseModel):
    alert_text: str

class ApprovalInput(BaseModel):
    approver: str

# Endpoints
@app.post("/api/alerts")
def receive_alert(payload: AlertInput, background_tasks: BackgroundTasks):
    """
    Receives an unstructured alert string, initializes a ticket, 
    and kicks off the Triage & Remediation planning in the background.
    """
    if not payload.alert_text.strip():
        raise HTTPException(status_code=400, detail="Alert text cannot be empty")
        
    incident_id = str(uuid.uuid4())[:8]
    
    # Initialize the incident in database
    memory.save_incident({
        "id": incident_id,
        "raw_alert": payload.alert_text,
        "status": "received",
        "triage_reasoning": "Waiting for Triage Agent...",
        "remediation_plan": "Waiting for Triage completion..."
    })
    
    # Process the flow in a background task to keep API highly responsive
    def process_flow():
        # 1. Run Triage
        agent.run_triage_agent(incident_id, payload.alert_text)
        # 2. Run Remediation selector
        remed = agent.run_remediation_agent(incident_id)
        
        # 3. If no approval is required, execute immediately
        if not remed.get("requires_approval"):
            agent.execute_remediation(incident_id, approved_by="system-autopilot")
            verify_res = agent.run_verification_agent(incident_id)
            # 4. Archive to Alibaba Cloud OSS
            full_incident = memory.get_incident(incident_id)
            alibaba_cloud_proof.archive_incident_to_oss(full_incident)
            
    background_tasks.add_task(process_flow)
    
    return {
        "incident_id": incident_id,
        "status": "received",
        "message": "Alert received. Multi-Agent orchestration started in background."
    }

@app.post("/api/webhooks/prometheus")
def prometheus_webhook(payload: dict, background_tasks: BackgroundTasks):
    """
    Webhook adapter for Prometheus Alertmanager.
    Converts Prometheus alert structures into unstructured text for Qwen Triage.
    """
    alerts = payload.get("alerts", [])
    if not alerts:
        raise HTTPException(status_code=400, detail="No alerts found in Prometheus payload")
        
    incident_ids = []
    for alert in alerts:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        
        alert_name = labels.get("alertname", "SystemAlert")
        instance = labels.get("instance", "unknown-host")
        severity = labels.get("severity", "medium")
        summary = annotations.get("summary", "")
        description = annotations.get("description", "")
        
        # Build alert text string for agent parsing
        alert_text = (
            f"PROMETHEUS ALERT Fired: {alert_name} on host {instance}.\n"
            f"Severity: {severity}\n"
            f"Summary: {summary}\n"
            f"Description: {description}"
        )
        
        incident_id = str(uuid.uuid4())[:8]
        incident_ids.append(incident_id)
        
        memory.save_incident({
            "id": incident_id,
            "raw_alert": alert_text,
            "status": "received",
            "triage_reasoning": "Prometheus alert received. Awaiting triage...",
            "remediation_plan": "Awaiting triage completion..."
        })
        
        # Define worker block closure
        def process_flow(inc_id=incident_id, text=alert_text):
            agent.run_triage_agent(inc_id, text)
            remed = agent.run_remediation_agent(inc_id)
            if not remed.get("requires_approval"):
                agent.execute_remediation(inc_id, approved_by="prometheus-autopilot")
                agent.run_verification_agent(inc_id)
                full_incident = memory.get_incident(inc_id)
                alibaba_cloud_proof.archive_incident_to_oss(full_incident)
                
        background_tasks.add_task(process_flow)
        
    return {
        "message": f"Successfully parsed and dispatched {len(alerts)} Prometheus alerts.",
        "incident_ids": incident_ids
    }

@app.post("/api/webhooks/sls")
def sls_webhook(payload: dict, background_tasks: BackgroundTasks):
    """
    Webhook adapter for Alibaba Cloud Simple Log Service (SLS) Alert manager.
    Parses the alert payload and dispatches the autonomous agent flow.
    """
    alert_name = payload.get("alert_name", "SLS Log Exception Alert")
    project = payload.get("project", "hack-ops-project")
    logstore = payload.get("logstore", "app-error-logstore")
    message = payload.get("alert_message", "OutOfMemoryError triggered in cluster")
    
    # Extract raw log context if fire_results are present
    fire_results = payload.get("fire_results", [])
    log_snippet = ""
    if fire_results and len(fire_results) > 0:
        import json
        log_snippet = "\nLog Traces:\n" + json.dumps(fire_results[0], indent=2)
        
    alert_text = f"SLS_ALERT: [{alert_name}] triggered in project '{project}' / Logstore '{logstore}'. Message: {message} {log_snippet}"
    
    # Process alert in background
    def process():
        agent.process_alert_full_flow(alert_text)
        
    background_tasks.add_task(process)
    return {"message": "SLS Webhook ingested successfully."}

@app.get("/api/incidents")
def get_incidents():
    """Returns all incident tickets."""
    return memory.get_all_incidents()

@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str):
    """Returns a specific incident ticket."""
    incident = memory.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident

@app.post("/api/incidents/{incident_id}/approve")
def approve_incident(incident_id: str, payload: ApprovalInput, background_tasks: BackgroundTasks):
    """
    Endpoint for Human-in-the-Loop approval.
    Executes the remediation tool and runs verification.
    """
    incident = memory.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
        
    if incident["status"] != "pending_approval":
        raise HTTPException(status_code=400, detail=f"Incident is in status '{incident['status']}', cannot approve.")
        
    # Process execution in background
    def execute_and_verify():
        agent.execute_remediation(incident_id, approved_by=payload.approver)
        agent.run_verification_agent(incident_id)
        
        # Archive completed run to Alibaba Cloud OSS
        final_incident = memory.get_incident(incident_id)
        alibaba_cloud_proof.archive_incident_to_oss(final_incident)
        
    background_tasks.add_task(execute_and_verify)
    
    return {
        "incident_id": incident_id,
        "status": "executing",
        "message": "Remediation approved. Commencing execution..."
    }

@app.post("/api/incidents/{incident_id}/reject")
def reject_incident(incident_id: str):
    """Rejects the planned remediation action and cancels the ticket."""
    incident = memory.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
        
    if incident["status"] != "pending_approval":
        raise HTTPException(status_code=400, detail="Incident not pending approval")
        
    memory.save_incident({
        "id": incident_id,
        "status": "failed",
        "verification_results": "Remediation plan rejected by operator. Ticket closed."
    })
    
    # Archive rejected log to OSS
    final_incident = memory.get_incident(incident_id)
    alibaba_cloud_proof.archive_incident_to_oss(final_incident)
    
    return {
        "incident_id": incident_id,
        "status": "failed",
        "message": "Remediation rejected. Ticket closed."
    }

@app.get("/api/memories")
def get_memories():
    """Fetches the cognitive experience database content."""
    conn = memory.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM experiences ORDER BY last_executed DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/oss/logs")
def get_oss_logs():
    """Lists logs currently backed up in Alibaba Cloud OSS / local mock archive."""
    return alibaba_cloud_proof.list_archived_logs()

@app.get("/api/kpi")
def get_kpi_metrics():
    """Calculates KPI telemetry metrics from the incidents database."""
    conn = memory.get_db_connection()
    cursor = conn.cursor()
    
    # 1. Total incidents collected
    cursor.execute("SELECT COUNT(*) as total FROM incidents")
    total_alerts = cursor.fetchone()["total"]
    
    # 2. Resolved alerts count
    cursor.execute("SELECT COUNT(*) as resolved FROM incidents WHERE status = 'resolved'")
    resolved_alerts = cursor.fetchone()["resolved"]
    
    # 3. Active alerts count
    cursor.execute("SELECT COUNT(*) as active FROM incidents WHERE status NOT IN ('resolved', 'failed')")
    active_alerts = cursor.fetchone()["active"]
    
    # 4. Pending approvals count
    cursor.execute("SELECT COUNT(*) as pending FROM incidents WHERE status = 'pending_approval'")
    pending_approvals = cursor.fetchone()["pending"]
    
    # 5. Success rate
    cursor.execute("SELECT COUNT(*) as failed FROM incidents WHERE status = 'failed'")
    failed_alerts = cursor.fetchone()["failed"]
    total_completed = resolved_alerts + failed_alerts
    success_rate = round((resolved_alerts / total_completed) * 100, 1) if total_completed > 0 else 100.0
    
    # 6. Auto-Remediation Rate (Resolved without human approval)
    cursor.execute("SELECT COUNT(*) as auto_resolved FROM incidents WHERE status = 'resolved' AND requires_approval = 0")
    auto_resolved = cursor.fetchone()["auto_resolved"]
    auto_remediation_rate = round((auto_resolved / resolved_alerts) * 100, 1) if resolved_alerts > 0 else 100.0
    
    # 7. Avg. Resolution Time (seconds)
    cursor.execute("SELECT AVG(resolution_time) as avg_time FROM incidents WHERE status = 'resolved' AND resolution_time IS NOT NULL")
    row = cursor.fetchone()
    avg_resolution_time = round(row["avg_time"], 1) if row and row["avg_time"] else 0.0
    
    conn.close()
    
    return {
        "total_alerts": total_alerts,
        "resolved_alerts": resolved_alerts,
        "active_alerts": active_alerts,
        "pending_approvals": pending_approvals,
        "success_rate": success_rate,
        "auto_remediation_rate": auto_remediation_rate,
        "avg_resolution_time": avg_resolution_time
    }

# Create static directory path
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

# Mount the static files (e.g. index.html) at root
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # Initialize DB tables
    memory.init_db()
    print("Starting FastAPI Dev Server at http://127.0.0.1:8000 ...")
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
