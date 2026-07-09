import os
import json
import time
import sqlite3
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("autopilot-ops")

# Reuse the database configurations and connectivity state from memory
from src.memory import ots_client, get_sqlite_conn

TABLE_NAME = os.environ.get("OTS_TABLE", "incident_sessions")

def init_events_db():
    """Initializes local SQLite events table if missing in dev mode."""
    if not ots_client:
        try:
            conn = get_sqlite_conn()
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS incident_events (
                session_id TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (session_id, timestamp)
            )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to initialize SQLite events table: {e}")

# Initialize events database
init_events_db()

def emit_event(
    session_id: str,
    event_type: str,
    payload: Dict[str, Any],
    timestamp_ms: Optional[int] = None
) -> None:
    """
    Writes a structured event to Tablestore OTS (or SQLite in local dev mode) for SSE consumption.
    """
    ts = timestamp_ms or int(time.time() * 1000)
    payload_str = json.dumps(payload, ensure_ascii=False)

    # 1. Tablestore OTS write path
    if ots_client:
        try:
            from tablestore import Row, Condition, RowExistenceExpectation
            
            primary_key = [('session_id', session_id), ('timestamp', ts)]
            attribute_columns = [
                ('event_type', event_type),
                ('payload', payload_str)
            ]
            
            try:
                ots_client.put_row(TABLE_NAME, Row(primary_key, attribute_columns), Condition(RowExistenceExpectation.IGNORE))
            except Exception:
                # If key collision, shift timestamp by 1ms and retry
                primary_key = [('session_id', session_id), ('timestamp', ts + 1)]
                ots_client.put_row(TABLE_NAME, Row(primary_key, attribute_columns), Condition(RowExistenceExpectation.IGNORE))
                
            logger.debug(f"[Event] {session_id} | {event_type} | ts={ts}")
            return
        except Exception as e:
            logger.error(f"[OTS Event Error] Fallback to SQLite: {e}")

    # 2. SQLite local fallback path
    try:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        try:
            cursor.execute("""
            INSERT INTO incident_events (session_id, timestamp, event_type, payload)
            VALUES (?, ?, ?, ?)
            """, (session_id, ts, event_type, payload_str))
        except sqlite3.IntegrityError:
            cursor.execute("""
            INSERT INTO incident_events (session_id, timestamp, event_type, payload)
            VALUES (?, ?, ?, ?)
            """, (session_id, ts + 1, event_type, payload_str))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[Event] Failed to emit {event_type} for {session_id}: {e}")
