import os
import uuid
import json
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from src import memory
from src import orchestrator

app = FastAPI(title="Qwen Autopilot Ops Dev Server", version="1.0.0")

# Enable CORS for frontend connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic Schemas
class AlertInput(BaseModel):
    alert_text: str

class ApprovalInput(BaseModel):
    approver: str
    approved: bool

# Endpoints
@app.post("/api/alerts")
def receive_alert(payload: AlertInput, background_tasks: BackgroundTasks):
    """Ingests alert payload and runs orchestrator flow in background."""
    if not payload.alert_text.strip():
        raise HTTPException(status_code=400, detail="Alert text cannot be empty")
        
    incident_id = str(uuid.uuid4())[:8]
    
    # Process orchestrator state transitions in background thread
    def run_flow():
        import asyncio
        asyncio.run(orchestrator.execute_full_remediation_flow(incident_id, payload.alert_text))
        
    background_tasks.add_task(run_flow)
    return {"incident_id": incident_id, "status": "processing"}

@app.post("/api/webhooks/prometheus")
def prometheus_webhook(payload: dict, background_tasks: BackgroundTasks):
    """Adapter for incoming Prometheus alert notifications."""
    alerts = payload.get("alerts", [])
    if not alerts:
        raise HTTPException(status_code=400, detail="No alerts found")
        
    incident_ids = []
    for alert in alerts:
        incident_id = str(uuid.uuid4())[:8]
        alert_name = alert.get("labels", {}).get("alertname", "PrometheusAlert")
        summary = alert.get("annotations", {}).get("summary", "System warning")
        alert_text = f"PROMETHEUS: [{alert_name}] {summary}"
        
        def run_flow(iid=incident_id, text=alert_text):
            import asyncio
            asyncio.run(orchestrator.execute_full_remediation_flow(iid, text))
            
        background_tasks.add_task(run_flow)
        incident_ids.append(incident_id)
        
    return {"incident_ids": incident_ids, "status": "processing"}

@app.post("/api/webhooks/sls")
def sls_webhook(payload: dict, background_tasks: BackgroundTasks):
    """Adapter for Alibaba Cloud SLS Alert notifications."""
    incident_id = str(uuid.uuid4())[:8]
    alert_text = payload.get("alert_message", "SLS log anomaly trigger")
    
    def run_flow():
        import asyncio
        asyncio.run(orchestrator.execute_full_remediation_flow(incident_id, alert_text))
        
    background_tasks.add_task(run_flow)
    return {"incident_id": incident_id, "status": "processing"}

@app.get("/api/incidents")
def get_incidents():
    return memory.get_all_incidents()

@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str):
    inc = memory.get_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    return inc

class ApprovalPayload(BaseModel):
    approver: Optional[str] = "Operator-HQ"

@app.post("/api/incidents/{incident_id}/approve")
def approve_incident(incident_id: str, payload: ApprovalPayload, background_tasks: BackgroundTasks):
    """Receives operator checkpoint approval and resumes execution."""
    def resume_flow():
        import asyncio
        asyncio.run(orchestrator.resume_execution_after_approval(incident_id, payload.approver, True))
        
    background_tasks.add_task(resume_flow)
    return {"status": "resumed"}

@app.post("/api/incidents/{incident_id}/reject")
def reject_incident(incident_id: str, background_tasks: BackgroundTasks):
    """Receives operator checkpoint rejection and escalates."""
    def resume_flow():
        import asyncio
        asyncio.run(orchestrator.resume_execution_after_approval(incident_id, "Operator-HQ", False))
        
    background_tasks.add_task(resume_flow)
    return {"status": "resumed"}

@app.get("/api/incidents/{incident_id}/stream")
def get_incident_stream(incident_id: str):
    """EventSource streaming endpoint for real-time state machine animations."""
    from fastapi.responses import StreamingResponse
    import time
    from src.fc_handler import get_events_since, is_terminal_state
    
    def event_generator():
        last_ts = 0
        while True:
            new_events = get_events_since(incident_id, last_ts)
            for evt in new_events:
                yield f"event: agent\ndata: {json.dumps(evt)}\n\n"
                last_ts = evt["timestamp"]
                
            if is_terminal_state(incident_id):
                yield f"event: agent\ndata: {json.dumps({'event': 'stream_end', 'session_id': incident_id})}\n\n"
                break
                
            time.sleep(0.5)
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/memories")
def get_memories():
    # Return experience registry logs
    conn = memory.get_sqlite_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM experiences ORDER BY last_executed DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/kpi")
def get_kpi():
    return memory.get_kpi_metrics()

@app.get("/api/oss/logs")
def get_oss_logs_stub():
    """Stub to prevent console polling errors on local dev frontend."""
    return []

# Serve static dashboard cockpit files
static_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.exists(static_path):
    app.mount("/", StaticFiles(directory=static_path, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.dev_server:app", host="0.0.0.0", port=8000, reload=True)
