import os
import time
import json
import logging

logger = logging.getLogger("ops-observability")

# Production SLS logs project configuration
SLS_PROJECT = os.environ.get("SLS_PROJECT", "")

def start_span(incident_id: str, state_name: str) -> dict:
    """Starts a trace span for a state machine transition."""
    return {
        "incident_id": incident_id,
        "span_name": f"state_{state_name}",
        "start_time": time.time()
    }

def end_span(span: dict, status: str = "SUCCESS", error_message: str = "") -> dict:
    """Closes the trace span, evaluates latency, and logs structured traces for SLS collection."""
    duration_sec = time.time() - span["start_time"]
    trace_payload = {
        "incident_id": span["incident_id"],
        "span_name": span["span_name"],
        "duration_ms": int(duration_sec * 1000),
        "status": status,
        "error_message": error_message,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    # Structured stdout print: Logtail captures these and sends them to SLS tracing dashboard
    logger.info(f"[TRACE_SPAN] {json.dumps(trace_payload)}")
    print(f"[TRACE_SPAN] {json.dumps(trace_payload)}")

    return trace_payload
