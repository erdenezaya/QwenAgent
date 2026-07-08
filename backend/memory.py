import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_ops.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the SQLite database schema if it doesn't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Incidents table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS incidents (
        id TEXT PRIMARY KEY,
        raw_alert TEXT NOT NULL,
        host TEXT,
        service TEXT,
        severity TEXT,
        status TEXT NOT NULL, -- 'triage', 'pending_approval', 'executing', 'resolved', 'failed'
        triage_reasoning TEXT,
        remediation_plan TEXT,
        requires_approval INTEGER DEFAULT 0,
        approved_by TEXT,
        execution_logs TEXT,
        verification_results TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)
    
    # Memory / Experience table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS experiences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service TEXT NOT NULL,
        alert_type TEXT NOT NULL,
        action_taken TEXT NOT NULL,
        success INTEGER NOT NULL, -- 1 for success, 0 for failure
        run_count INTEGER DEFAULT 1,
        last_executed TEXT NOT NULL
    )
    """)
    
    # Pre-populate some historical experiences to demonstrate Qwen's ability to learn/recall
    cursor.execute("SELECT COUNT(*) as cnt FROM experiences")
    if cursor.fetchone()["cnt"] == 0:
        historical_data = [
            ("tomcat", "high CPU usage", "restart tomcat service", 1, 3, "2026-07-05 10:00:00"),
            ("mysql", "database connection failed", "restart mysql service", 1, 2, "2026-07-06 14:30:00"),
            ("nginx", "out of memory", "clear nginx temp cache files", 1, 4, "2026-07-07 09:15:00"),
            ("disk-storage", "disk full", "clear syslog archives and tmp logs", 1, 5, "2026-07-08 08:00:00"),
            ("disk-storage", "disk full", "delete system configuration files", 0, 1, "2026-07-04 11:20:00") # Failed attempt
        ]
        cursor.executemany("""
        INSERT INTO experiences (service, alert_type, action_taken, success, run_count, last_executed)
        VALUES (?, ?, ?, ?, ?, ?)
        """, historical_data)
        
    conn.commit()
    conn.close()

def save_incident(incident_data: dict):
    """Inserts or updates an incident record."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Ensure times are strings
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Fetch existing to preserve or decide action
    cursor.execute("SELECT id FROM incidents WHERE id = ?", (incident_data.get("id"),))
    exists = cursor.fetchone()
    
    if not exists:
        cursor.execute("""
        INSERT INTO incidents (
            id, raw_alert, host, service, severity, status, 
            triage_reasoning, remediation_plan, requires_approval, 
            approved_by, execution_logs, verification_results, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            incident_data.get("id"),
            incident_data.get("raw_alert", ""),
            incident_data.get("host", ""),
            incident_data.get("service", ""),
            incident_data.get("severity", "medium"),
            incident_data.get("status", "triage"),
            incident_data.get("triage_reasoning", ""),
            incident_data.get("remediation_plan", ""),
            1 if incident_data.get("requires_approval") else 0,
            incident_data.get("approved_by"),
            incident_data.get("execution_logs", ""),
            incident_data.get("verification_results", ""),
            now_str,
            now_str
        ))
    else:
        # Build update query dynamically based on provided fields
        fields_to_update = []
        params = []
        for key in ["host", "service", "severity", "status", "triage_reasoning", 
                    "remediation_plan", "requires_approval", "approved_by", 
                    "execution_logs", "verification_results"]:
            if key in incident_data:
                val = incident_data[key]
                if key == "requires_approval":
                    val = 1 if val else 0
                fields_to_update.append(f"{key} = ?")
                params.append(val)
        
        fields_to_update.append("updated_at = ?")
        params.append(now_str)
        
        params.append(incident_data["id"])
        
        query = f"UPDATE incidents SET {', '.join(fields_to_update)} WHERE id = ?"
        cursor.execute(query, tuple(params))
        
    conn.commit()
    conn.close()

def get_incident(incident_id: str) -> dict:
    """Retrieves a single incident by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def get_all_incidents() -> list:
    """Retrieves all incidents sorted by creation date descending."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM incidents ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_relevant_memories(service: str, alert_type: str) -> list:
    """
    Searches the experiences table for actions taken on similar services/alert types.
    Matches either the service directly or via simple keyword matching.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Query experiences that match the service or are related to the alert type
    cursor.execute("""
    SELECT * FROM experiences 
    WHERE LOWER(service) LIKE ? OR LOWER(alert_type) LIKE ? 
    ORDER BY success DESC, run_count DESC
    """, (f"%{service.lower()}%", f"%{alert_type.lower()}%"))
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def record_experience(service: str, alert_type: str, action_taken: str, success: bool):
    """Records a new agent remediation experience (or increments run_count of existing)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    success_val = 1 if success else 0
    
    # Check if this exact remediation has been recorded
    cursor.execute("""
    SELECT id, run_count FROM experiences 
    WHERE LOWER(service) = ? AND LOWER(alert_type) = ? AND LOWER(action_taken) = ? AND success = ?
    """, (service.lower(), alert_type.lower(), action_taken.lower(), success_val))
    
    row = cursor.fetchone()
    if row:
        cursor.execute("""
        UPDATE experiences SET run_count = run_count + 1, last_executed = ? 
        WHERE id = ?
        """, (now_str, row["id"]))
    else:
        cursor.execute("""
        INSERT INTO experiences (service, alert_type, action_taken, success, run_count, last_executed)
        VALUES (?, ?, ?, ?, 1, ?)
        """, (service, alert_type, action_taken, success_val, now_str))
        
    conn.commit()
    conn.close()

# Initialize database on import
if __name__ not in ("__main__",):
    init_db()
