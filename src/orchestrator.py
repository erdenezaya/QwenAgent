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
from src.events import emit_event

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
    Main state machine orchestrator loop. Used locally by dev_server
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
    start_ts = int(start_time * 1000)
    
    while state not in (IncidentState.REPORT, IncidentState.ESCALATED):
        span = observability.start_span(incident_id, state.value)
        log_msg = f"Orchestrator transition: entering state '{state.value}'"
        append_db_log(incident_id, log_msg)
        
        try:
            if state == IncidentState.TRIAGE:
                # Emit state transition
                emit_event(incident_id, "state_transition", {
                    "to_state": "triage",
                    "from_state": None,
                    "metadata": {"severity": alert.get("severity", "critical")}
                })
                
                logs = await parse_alert_logs(alert)
                session["logs"] = logs
                append_db_log(incident_id, f"Triage diagnostic SLS logs fetched successfully.")
                
                emit_event(incident_id, "tool_output", {
                    "tool": "sls",
                    "output": f"Retrieved {len(logs)} log entries from SLS",
                    "latency_ms": int((time.time() - start_time) * 1000)
                })
                
                state = IncidentState.DIAGNOSE
                observability.end_span(span, "SUCCESS")
                
            elif state == IncidentState.DIAGNOSE:
                # Emit state transition
                emit_event(incident_id, "state_transition", {
                    "to_state": "diagnose",
                    "from_state": "triage",
                    "metadata": {"summary": "SLS log ingestion complete"}
                })
                
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
                # Emit state transition
                emit_event(incident_id, "state_transition", {
                    "to_state": "plan",
                    "from_state": "diagnose",
                    "metadata": {"summary": diagnosis.get("root_cause", "Unknown")}
                })
                
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
                
                # Emit safety check event
                emit_event(incident_id, "safety_check", {
                    "tool": "safety",
                    "message": f"Risk score: {risk:.2f} | Command: {plan.get('command')}",
                    "risk_score": risk,
                    "approved": risk < 0.7
                })
                
                if requires_approval:
                    memory.save_incident({
                        "id": incident_id,
                        "status": IncidentState.AWAITING_APPROVAL.value
                    })
                    append_db_log(incident_id, "HITL Gate Block: Remediation plan requires manual Operator Approval.")
                    
                    emit_event(incident_id, "state_transition", {
                        "to_state": "awaiting_approval",
                        "from_state": "plan",
                        "metadata": {
                            "risk_score": risk,
                            "command": plan.get("command"),
                            "target_host": diagnosis.get("host"),
                            "summary": f"HIGH RISK ({risk:.2f}) - awaiting human approval"
                        }
                    })
                    
                    state = IncidentState.AWAITING_APPROVAL
                    observability.end_span(span, "AWAITING_APPROVAL")
                    break
                else:
                    state = IncidentState.EXECUTE
                    observability.end_span(span, "SUCCESS")
                    
            elif state == IncidentState.AWAITING_APPROVAL:
                break
                
            elif state == IncidentState.EXECUTE:
                emit_event(incident_id, "state_transition", {
                    "to_state": "executing",
                    "from_state": "plan",
                    "metadata": {"command": plan.get("command")}
                })
                
                memory.save_incident({
                    "id": incident_id,
                    "status": IncidentState.EXECUTE.value
                })
                result = await execute_remediation(plan)
                session["exec_result"] = result
                
                emit_event(incident_id, "tool_output", {
                    "tool": "executor",
                    "output": result.get("stdout") if result.get("success") else result.get("stderr"),
                    "latency_ms": 1000
                })
                
                if result.get("success"):
                    append_db_log(incident_id, f"Remediation execution succeeded:\n{result.get('stdout')}")
                    state = IncidentState.VERIFY
                else:
                    append_db_log(incident_id, f"Remediation execution failed:\n{result.get('stderr')}")
                    state = IncidentState.ESCALATED
                    
                observability.end_span(span, "SUCCESS" if result.get("success") else "FAILED", result.get("stderr", ""))
                
            elif state == IncidentState.VERIFY:
                emit_event(incident_id, "state_transition", {
                    "to_state": "verify",
                    "from_state": "executing",
                    "metadata": {}
                })
                
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
        
        emit_event(incident_id, "state_transition", {
            "to_state": "resolved",
            "from_state": "verify",
            "metadata": {"summary": f"Resolved in {elapsed}s"}
        })
        
        emit_event(incident_id, "stream_end", {
            "final_state": "resolved",
            "total_duration_ms": int(time.time() * 1000) - start_ts
        })
        
        await upload_postmortem(session)
        
    elif state == IncidentState.ESCALATED:
        memory.save_incident({
            "id": incident_id,
            "status": "failed",
            "resolution_summary": "Remediation failed or was rejected. Escalated to on-call."
        })
        append_db_log(incident_id, "Incident failed and escalated to manual operator intervention.")
        
        emit_event(incident_id, "state_transition", {
            "to_state": "failed",
            "from_state": "verify",
            "metadata": {"summary": "Remediation failed or was rejected."}
        })
        
        emit_event(incident_id, "stream_end", {
            "final_state": "failed",
            "total_duration_ms": int(time.time() * 1000) - start_ts
        })
        
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
        
        emit_event(incident_id, "state_transition", {
            "to_state": "failed",
            "from_state": "awaiting_approval",
            "metadata": {"summary": f"Remediation rejected by operator: {approved_by}"}
        })
        
        emit_event(incident_id, "stream_end", {
            "final_state": "failed",
            "total_duration_ms": 0
        })
        
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
    
    emit_event(incident_id, "state_transition", {
        "to_state": "executing",
        "from_state": "awaiting_approval",
        "metadata": {"approved_by": approved_by, "command": plan.get("command")}
    })
    
    start_time = time.time()
    start_ts = int(start_time * 1000)
    span = observability.start_span(incident_id, "executing")
    result = await execute_remediation(plan)
    session["exec_result"] = result
    
    emit_event(incident_id, "tool_output", {
        "tool": "executor",
        "output": result.get("stdout") if result.get("success") else result.get("stderr"),
        "latency_ms": 1000
    })
    
    if result.get("success"):
        append_db_log(incident_id, f"Remediation execution succeeded:\n{result.get('stdout')}")
        observability.end_span(span, "SUCCESS")
        
        # Verify
        span_v = observability.start_span(incident_id, "verify")
        
        emit_event(incident_id, "state_transition", {
            "to_state": "verify",
            "from_state": "executing",
            "metadata": {}
        })
        
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
            
            emit_event(incident_id, "state_transition", {
                "to_state": "resolved",
                "from_state": "verify",
                "metadata": {"summary": f"Resolved in {elapsed}s"}
            })
            
            emit_event(incident_id, "stream_end", {
                "final_state": "resolved",
                "total_duration_ms": int(time.time() * 1000) - start_ts
            })
            
            await upload_postmortem(session)
        else:
            append_db_log(incident_id, "Post-remediation diagnostics failed. Service remains unhealthy.")
            memory.save_incident({
                "id": incident_id,
                "status": "failed",
                "resolution_summary": "Remediation failed or was rejected. Escalated to on-call."
            })
            observability.end_span(span_v, "FAILED")
            
            emit_event(incident_id, "state_transition", {
                "to_state": "failed",
                "from_state": "verify",
                "metadata": {"summary": "Post-remediation check failed."}
            })
            
            emit_event(incident_id, "stream_end", {
                "final_state": "failed",
                "total_duration_ms": int(time.time() * 1000) - start_ts
            })
            
            await upload_postmortem(session)
    else:
        append_db_log(incident_id, f"Remediation execution failed:\n{result.get('stderr')}")
        observability.end_span(span, "FAILED", result.get("stderr"))
        memory.save_incident({
            "id": incident_id,
            "status": "failed",
            "resolution_summary": "Remediation failed or was rejected. Escalated to on-call."
        })
        
        emit_event(incident_id, "state_transition", {
            "to_state": "failed",
            "from_state": "executing",
            "metadata": {"summary": "Execution check failed."}
        })
        
        emit_event(incident_id, "stream_end", {
            "final_state": "failed",
            "total_duration_ms": int(time.time() * 1000) - start_ts
        })
        
        await upload_postmortem(session)
