import os
import json
import uuid
import time
import asyncio
import logging
from enum import Enum

from src import memory
from src import observability
from src.qwen_client import QwenRouter
from src.tools.log_parser import parse_alert_logs
from src.tools.remediation import execute_remediation
from src.tools.health_check import verify_system_health
from src.tools.postmortem import upload_postmortem
from src.safety.risk_scorer import score_blast_radius

logger = logging.getLogger("autopilot-ops-orchestrator")

class IncidentState(Enum):
    TRIAGE = "triage"
    DIAGNOSE = "diagnose"
    PLAN = "plan"
    AWAITING_APPROVAL = "pending_approval"
    EXECUTE = "executing"
    VERIFY = "verify"
    REPORT = "resolved"
    ESCALATED = "failed"

def append_db_log(incident_id: str, message: str):
    """Utility to append structured logs to database."""
    incident = memory.get_incident(incident_id)
    if not incident:
        return
    try:
        logs = json.loads(incident.get("execution_logs", "[]"))
    except Exception:
        logs = []
    logs.append(f"[{time.strftime('%H:%M:%S')}] {message}")
    memory.save_incident({
        "id": incident_id,
        "execution_logs": json.dumps(logs)
    })

async def execute_full_remediation_flow(incident_id: str, alert_text: str):
    """
    Main state machine orchestrator loop. Used locally by FastAPI / dev_server
    and in production serverless runtimes.
    """
    alert = {"id": incident_id, "alert_text": alert_text}
    state = IncidentState.TRIAGE
    session = {
        "alert": alert,
        "logs": "",
        "diagnosis": {},
        "plan": {},
        "exec_result": {},
        "risk_level": 0.0,
        "history": [],
        "id": incident_id
    }
    
    # Save initial state to memory
    memory.save_incident({
        "id": incident_id,
        "raw_alert": alert_text,
        "status": state.value,
        "execution_logs": json.dumps([f"[{time.strftime('%H:%M:%S')}] Started orchestrator flow for {incident_id}"])
    })
    
    start_time = time.time()
    
    while state not in (IncidentState.REPORT, IncidentState.ESCALATED):
        span = observability.start_span(incident_id, state.value)
        log_msg = f"Orchestrator transition: entering state '{state.value}'"
        append_db_log(incident_id, log_msg)
        
        try:
            if state == IncidentState.TRIAGE:
                logs = await parse_alert_logs(alert)
                session["logs"] = logs
                append_db_log(incident_id, f"Triage diagnostic SLS logs fetched successfully.")
                state = IncidentState.DIAGNOSE
                observability.end_span(span, "SUCCESS")
                
            elif state == IncidentState.DIAGNOSE:
                diagnosis = await QwenRouter.diagnose(session)
                session["diagnosis"] = diagnosis
                
                # Check pattern warnings
                recent_count = memory.count_recent_alerts(diagnosis.get("service", ""), hours=24)
                pattern = "None"
                if recent_count > 0:
                    pattern = f"Recurring {diagnosis.get('service')} alerts detected: {recent_count} times in 24h."
                
                memory.save_incident({
                    "id": incident_id,
                    "status": "triage_completed",
                    "host": diagnosis.get("host"),
                    "service": diagnosis.get("service"),
                    "severity": diagnosis.get("severity"),
                    "triage_reasoning": diagnosis.get("triage_reasoning"),
                    "root_cause": diagnosis.get("root_cause"),
                    "pattern_detected": pattern
                })
                
                append_db_log(incident_id, f"Qwen diagnosis completed. Service: '{diagnosis.get('service')}', Host: '{diagnosis.get('host')}'")
                state = IncidentState.PLAN
                observability.end_span(span, "SUCCESS")
                
            elif state == IncidentState.PLAN:
                plan = await QwenRouter.plan_remediation(session)
                session["plan"] = plan
                
                # Score risk before execution
                risk = score_blast_radius(plan)
                session["risk_level"] = risk
                
                requires_approval = 1 if risk >= 0.7 else 0
                effort = "High" if risk >= 0.7 else "Low"
                downtime = "Yes" if risk >= 0.7 else "No"
                
                memory.save_incident({
                    "id": incident_id,
                    "remediation_plan": plan.get("command"),
                    "requires_approval": requires_approval,
                    "predicted_effort": effort,
                    "predicted_downtime": downtime,
                    "risk_level": str(risk)
                })
                
                append_db_log(incident_id, f"Remediation plan generated: '{plan.get('command')}' (Risk level: {risk})")
                
                if requires_approval:
                    memory.save_incident({
                        "id": incident_id,
                        "status": IncidentState.AWAITING_APPROVAL.value
                    })
                    append_db_log(incident_id, "HITL Gate Block: Remediation plan requires manual Operator Approval.")
                    state = IncidentState.AWAITING_APPROVAL
                    observability.end_span(span, "AWAITING_APPROVAL")
                    break
                else:
                    state = IncidentState.EXECUTE
                    observability.end_span(span, "SUCCESS")
                    
            elif state == IncidentState.AWAITING_APPROVAL:
                break
                
            elif state == IncidentState.EXECUTE:
                memory.save_incident({
                    "id": incident_id,
                    "status": IncidentState.EXECUTE.value
                })
                result = await execute_remediation(plan)
                session["exec_result"] = result
                
                if result.get("success"):
                    append_db_log(incident_id, f"Remediation execution succeeded:\n{result.get('stdout')}")
                    state = IncidentState.VERIFY
                else:
                    append_db_log(incident_id, f"Remediation execution failed:\n{result.get('stderr')}")
                    state = IncidentState.ESCALATED
                    
                observability.end_span(span, "SUCCESS" if result.get("success") else "FAILED", result.get("stderr", ""))
                
            elif state == IncidentState.VERIFY:
                healthy = await verify_system_health(alert)
                session["verified"] = healthy
                
                if healthy:
                    append_db_log(incident_id, "Post-remediation port diagnostics succeeded. Target health nominal.")
                    state = IncidentState.REPORT
                else:
                    append_db_log(incident_id, "Post-remediation diagnostics failed. Service remains unhealthy.")
                    state = IncidentState.ESCALATED
                    
                observability.end_span(span, "SUCCESS" if healthy else "FAILED")
                
        except Exception as e:
            append_db_log(incident_id, f"Critical exception during state '{state.value}': {e}")
            state = IncidentState.ESCALATED
            observability.end_span(span, "ERROR", str(e))
            
    # Resolution paths
    if state == IncidentState.REPORT:
        elapsed = int(time.time() - start_time)
        memory.save_incident({
            "id": incident_id,
            "status": "resolved",
            "resolution_summary": "Incident resolved autonomously by Qwen agents.",
            "resolution_time": elapsed
        })
        append_db_log(incident_id, f"Incident resolved successfully in {elapsed}s.")
        await upload_postmortem(session)
        
    elif state == IncidentState.ESCALATED:
        memory.save_incident({
            "id": incident_id,
            "status": "failed",
            "resolution_summary": "Remediation failed or was rejected. Escalated to on-call."
        })
        append_db_log(incident_id, "Incident failed and escalated to manual operator intervention.")
        await upload_postmortem(session)

async def resume_execution_after_approval(incident_id: str, approved_by: str, approved: bool):
    """Resumes execution state machine after Operator Approval callback."""
    incident = memory.get_incident(incident_id)
    if not incident:
        return
        
    if not approved:
        memory.save_incident({
            "id": incident_id,
            "status": "failed",
            "approved_by": approved_by,
            "resolution_summary": f"Remediation rejected by {approved_by}."
        })
        append_db_log(incident_id, f"Remediation plan rejected by operator: {approved_by}")
        # Run upload postmortem representing escalation
        alert = {"id": incident_id, "alert_text": incident.get("raw_alert")}
        session = {"alert": alert, "diagnosis": {"service": incident.get("service")}, "plan": {"command": incident.get("remediation_plan")}}
        await upload_postmortem(session)
        return

    memory.save_incident({
        "id": incident_id,
        "approved_by": approved_by,
        "status": "executing"
    })
    append_db_log(incident_id, f"Remediation plan approved by operator: {approved_by}. Resuming execution.")

    # Continue loop starting at EXECUTE
    plan = {
        "command": incident.get("remediation_plan"),
        "id": "remediation-approved-id"
    }
    alert = {"id": incident_id, "alert_text": incident.get("raw_alert")}
    session = {
        "alert": alert,
        "logs": "",
        "diagnosis": {"service": incident.get("service"), "host": incident.get("host")},
        "plan": plan,
        "exec_result": {},
        "id": incident_id
    }
    
    start_time = time.time()
    span = observability.start_span(incident_id, "executing")
    result = await execute_remediation(plan)
    session["exec_result"] = result
    
    if result.get("success"):
        append_db_log(incident_id, f"Remediation execution succeeded:\n{result.get('stdout')}")
        observability.end_span(span, "SUCCESS")
        
        # Verify
        span_v = observability.start_span(incident_id, "verify")
        healthy = await verify_system_health(alert)
        if healthy:
            append_db_log(incident_id, "Post-remediation port diagnostics succeeded. Target health nominal.")
            elapsed = int(time.time() - start_time)
            memory.save_incident({
                "id": incident_id,
                "status": "resolved",
                "resolution_summary": "Incident resolved autonomously by Qwen agents.",
                "resolution_time": elapsed
            })
            append_db_log(incident_id, f"Incident resolved successfully in {elapsed}s.")
            observability.end_span(span_v, "SUCCESS")
            await upload_postmortem(session)
        else:
            append_db_log(incident_id, "Post-remediation diagnostics failed. Service remains unhealthy.")
            memory.save_incident({
                "id": incident_id,
                "status": "failed",
                "resolution_summary": "Remediation failed or was rejected. Escalated to on-call."
            })
            observability.end_span(span_v, "FAILED")
            await upload_postmortem(session)
    else:
        append_db_log(incident_id, f"Remediation execution failed:\n{result.get('stderr')}")
        observability.end_span(span, "FAILED", result.get("stderr"))
        memory.save_incident({
            "id": incident_id,
            "status": "failed",
            "resolution_summary": "Remediation failed or was rejected. Escalated to on-call."
        })
        await upload_postmortem(session)

# ----------------- FC3 WSGI HANDLER -----------------
def handler(environ, start_response):
    """
    Alibaba Cloud Function Compute 3.0 WSGI HTTP Trigger entry point.
    """
    try:
        request_method = environ.get('REQUEST_METHOD', 'GET')
        path_info = environ.get('PATH_INFO', '/')

        # 1. Health check liveness endpoint for judges
        if path_info == '/api/health' and request_method == 'GET':
            status = '200 OK'
            response_headers = [('Content-type', 'application/json')]
            start_response(status, response_headers)
            return [json.dumps({"status": "healthy", "service": "Qwen Autopilot Ops Serverless Runtime"}).encode('utf-8')]

        # 2. Trigger webhook ingestion endpoint
        elif path_info == '/api/webhooks/sls' and request_method == 'POST':
            try:
                request_body_size = int(environ.get('CONTENT_LENGTH', 0))
                request_body = environ['wsgi.input'].read(request_body_size)
                payload = json.loads(request_body)
            except Exception:
                payload = {}

            incident_id = str(uuid.uuid4())[:8]
            alert_text = payload.get("alert_message", "SLS High CPU trigger exception")

            # Run state machine loop synchronously under Function Compute invocation request
            asyncio.run(execute_full_remediation_flow(incident_id, alert_text))

            status = '202 Accepted'
            response_headers = [('Content-type', 'application/json')]
            start_response(status, response_headers)
            return [json.dumps({"incident_id": incident_id, "status": "processing"}).encode('utf-8')]

        else:
            status = '404 Not Found'
            response_headers = [('Content-type', 'application/json')]
            start_response(status, response_headers)
            return [json.dumps({"error": "Path not found"}).encode('utf-8')]

    except Exception as e:
        status = '500 Internal Server Error'
        response_headers = [('Content-type', 'application/json')]
        start_response(status, response_headers)
        return [json.dumps({"error": str(e)}).encode('utf-8')]
