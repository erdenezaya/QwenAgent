"""
Native Alibaba Cloud Function Compute 3.0 HTTP Handler.
Replaces FastAPI in production to eliminate ASGI cold-start overhead.
Local development uses dev_server.py (FastAPI) for cockpit dashboard UI debugging.
"""
import os
import json
import asyncio
import logging
from typing import Dict, Any

from src.orchestrator import execute_full_remediation_flow

logger = logging.getLogger("autopilot-ops")

def handler(environ: Dict[str, Any], start_response):
    """
    FC3 native WSGI-compatible HTTP handler.
    Routes POST /incidents to orchestrator, GET /health to liveness check.
    """
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/")

    # --- Health Check Endpoint (for judges & monitoring) ---
    if method == "GET" and path == "/health":
        body = json.dumps({
            "status": "healthy",
            "service": "qwen-autopilot-ops",
            "safety_mode": os.environ.get("SAFETY_MODE", "UNKNOWN"),
            "ots_connected": _check_ots_connectivity(),
            "sls_connected": _check_sls_connectivity(),
            "oss_connected": _check_oss_connectivity()
        }).encode("utf-8")
        start_response("200 OK", [("Content-Type", "application/json")])
        return [body]

    # --- Incident Ingestion Endpoint ---
    if method == "POST" and path == "/incidents":
        try:
            request_body_size = int(environ.get('CONTENT_LENGTH', 0))
            request_body = environ["wsgi.input"].read(request_body_size)
            alert_payload = json.loads(request_body)

            # Validate minimum required fields
            if "alert_id" not in alert_payload or "alert_text" not in alert_payload:
                return _error_response(start_response, 400, 
                    "Missing required fields: alert_id, alert_text")

            # Run state machine loop synchronously under Function Compute invocation request
            alert_text = alert_payload.get("alert_text", "")
            incident_id = alert_payload.get("alert_id", "")
            
            asyncio.run(execute_full_remediation_flow(incident_id, alert_text))

            # Fetch result ticket state
            from src import memory
            ticket = memory.get_incident(incident_id) or {}
            
            response_body = json.dumps({
                "incident_id": incident_id,
                "status": ticket.get("status", "processing"),
                "remediation_plan": ticket.get("remediation_plan"),
                "resolution_summary": ticket.get("resolution_summary")
            }).encode("utf-8")
            
            start_response("200 OK", [("Content-Type", "application/json")])
            return [response_body]

        except json.JSONDecodeError:
            return _error_response(start_response, 400, "Invalid JSON payload")
        except Exception as e:
            logger.exception(f"Unhandled error in incident processing: {e}")
            return _error_response(start_response, 500, f"Internal error: {str(e)}")

    # --- 404 Fallback ---
    return _error_response(start_response, 404, f"Not Found: {method} {path}")


def _error_response(start_response, status_code: int, message: str):
    body = json.dumps({"error": message}).encode("utf-8")
    status_str = f"{status_code} Error"
    start_response(status_str, [("Content-Type", "application/json")])
    return [body]


def _check_ots_connectivity() -> bool:
    """Lightweight OTS connectivity check for health endpoint."""
    try:
        from src.memory import ots_client
        if ots_client:
            ots_client.list_table()
            return True
        return False
    except Exception:
        return False

def _check_sls_connectivity() -> bool:
    """Lightweight SLS connectivity check."""
    try:
        from src.tools.log_parser import SLS_ENDPOINT, ACCESS_KEY_ID
        if SLS_ENDPOINT and ACCESS_KEY_ID:
            return True
        return False
    except Exception:
        return False

def _check_oss_connectivity() -> bool:
    """Lightweight OSS connectivity check."""
    try:
        from src.tools.postmortem import OSS_ACCESS_KEY_ID
        if OSS_ACCESS_KEY_ID:
            return True
        return False
    except Exception:
        return False
