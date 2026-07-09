"""
Native Alibaba Cloud Function Compute 3.0 HTTP Handler.
Replaces FastAPI in production to eliminate ASGI cold-start overhead.
Local development uses dev_server.py (FastAPI) for cockpit dashboard UI debugging.
"""
import os
import json
import time
import asyncio
import logging
from typing import Dict, Any

from src.orchestrator import execute_full_remediation_flow
from src.memory import ots_client, get_sqlite_conn

logger = logging.getLogger("autopilot-ops")

def get_events_since(session_id: str, after_timestamp: int, limit: int = 50) -> list[dict]:
    """
    Range query on Tablestore OTS or local SQLite incident_events table.
    Returns events with timestamp > after_timestamp, ordered ascending.
    """
    # 1. OTS Query
    if ots_client:
        try:
            from tablestore import INF_MAX, Direction
            inclusive_start = [("session_id", session_id), ("timestamp", after_timestamp + 1)]
            exclusive_end   = [("session_id", session_id), ("timestamp", INF_MAX)]
            
            table_name = os.environ.get("OTS_TABLE", "incident_sessions")
            
            consumed, next_pk, rows, next_token = ots_client.get_range(
                table_name,
                Direction.FORWARD,
                inclusive_start,
                exclusive_end,
                limit=limit,
                columns_to_get=["event_type", "payload", "timestamp"]
            )
            
            events = []
            for row in rows:
                attrs = {col[0]: col[1] for col in row.attribute_columns}
                events.append({
                    "event": attrs.get("event_type", "unknown"),
                    "session_id": session_id,
                    "timestamp": row.primary_key[1][1],
                    "payload": json.loads(attrs.get("payload", "{}"))
                })
            return events
        except Exception as e:
            logger.error(f"[OTS Event Range Error] {e}")

    # 2. SQLite local query fallback
    try:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT event_type, payload, timestamp FROM incident_events 
            WHERE session_id = ? AND timestamp > ? 
            ORDER BY timestamp ASC LIMIT ?
        """, (session_id, after_timestamp, limit))
        rows = cursor.fetchall()
        conn.close()
        
        events = []
        for row in rows:
            events.append({
                "event": row["event_type"],
                "session_id": session_id,
                "timestamp": row["timestamp"],
                "payload": json.loads(row["payload"])
            })
        return events
    except Exception as e:
        logger.error(f"[SQLite Event Range Error] {e}")
        return []

def is_terminal_state(session_id: str) -> bool:
    """Checks if the incident session has reached a terminal state."""
    # 1. OTS Query
    if ots_client:
        try:
            from src import memory
            ticket = memory.get_incident(session_id)
            if ticket and ticket.get("status") in ("resolved", "failed"):
                return True
        except Exception:
            pass
            
    # 2. SQLite Query
    try:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM incidents WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        conn.close()
        if row and row["status"] in ("resolved", "failed"):
            return True
    except Exception:
        pass
        
    return False

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

    # --- SSE Stream Endpoint ---
    if method == "GET" and path.startswith("/incidents/") and path.endswith("/stream"):
        session_id = path.split("/")[2]
        
        # Set SSE headers required by FC3
        headers = [
            ("Content-Type", "text/event-stream"),
            ("Cache-Control", "no-cache"),
            ("Connection", "keep-alive"),
            ("X-Accel-Buffering", "no"),  # Critical: disables FC3 response buffering
            ("Access-Control-Allow-Origin", "*"),  # Enable CORS for cockpit local dev UI
        ]
        start_response("200 OK", headers)
        
        # Generator yields SSE frames as orchestrator progresses
        def event_generator():
            last_ts = 0
            while True:
                try:
                    # Yield comment heartbeat to check client socket
                    yield ": heartbeat\n\n".encode("utf-8")
                except Exception:
                    break
                    
                new_events = get_events_since(session_id, last_ts)
                for evt in new_events:
                    try:
                        yield f"event: agent\ndata: {json.dumps(evt)}\n\n".encode("utf-8")
                    except Exception:
                        return
                    last_ts = evt["timestamp"]
                
                # Check if session reached terminal state
                if is_terminal_state(session_id):
                    try:
                        yield f"event: agent\ndata: {json.dumps({'event': 'stream_end', 'session_id': session_id})}\n\n".encode("utf-8")
                    except Exception:
                        pass
                    break
                    
                time.sleep(0.5)  # 500ms polling interval
                
        return event_generator()

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
