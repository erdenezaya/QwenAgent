import os
import json
import sqlite3
from datetime import datetime

# Local DB Config
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_ops.db")

# Alibaba Cloud Tablestore (OTS) Config
OTS_INSTANCE = os.environ.get("OTS_INSTANCE", "")
OTS_ENDPOINT = os.environ.get("OTS_ENDPOINT", "")
ACCESS_KEY_ID = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
ACCESS_KEY_SECRET = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")

ots_client = None
if OTS_INSTANCE and ACCESS_KEY_ID and ACCESS_KEY_SECRET:
    try:
        from tablestore import OTSClient
        ots_client = OTSClient(OTS_ENDPOINT, ACCESS_KEY_ID, ACCESS_KEY_SECRET, OTS_INSTANCE)
    except Exception as e:
        print(f"[Warning] Failed to initialize Tablestore client, using SQLite fallback: {e}")

# ----------------- SQLITE RUNTIME FALLBACK -----------------
def get_sqlite_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes local SQLite database schema."""
    conn = get_sqlite_conn()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS incidents (
        id TEXT PRIMARY KEY,
        raw_alert TEXT NOT NULL,
        host TEXT,
        service TEXT,
        severity TEXT,
        status TEXT NOT NULL,
        triage_reasoning TEXT,
        remediation_plan TEXT,
        requires_approval INTEGER DEFAULT 0,
        approved_by TEXT,
        execution_logs TEXT,
        verification_results TEXT,
        root_cause TEXT,
        resolution_summary TEXT,
        pattern_detected TEXT,
        predicted_effort TEXT,
        predicted_downtime TEXT,
        risk_level TEXT,
        resolution_time INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS experiences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service TEXT NOT NULL,
        alert_type TEXT NOT NULL,
        action_taken TEXT NOT NULL,
        success INTEGER NOT NULL,
        run_count INTEGER DEFAULT 1,
        last_executed TEXT NOT NULL
    )
    """)
    # Seed experience bank if empty
    cursor.execute("SELECT COUNT(*) as cnt FROM experiences")
    if cursor.fetchone()["cnt"] == 0:
        cursor.executemany("""
        INSERT INTO experiences (service, alert_type, action_taken, success, run_count, last_executed)
        VALUES (?, ?, ?, ?, ?, ?)
        """, [
            ("tomcat", "high CPU usage", "restart tomcat service", 1, 3, "2026-07-05 10:00:00"),
            ("mysql", "database connection failed", "restart mysql service", 1, 2, "2026-07-06 14:30:00"),
            ("nginx", "out of memory", "clear nginx temp cache files", 1, 4, "2026-07-07 09:15:00"),
            ("disk-storage", "disk full", "clear syslog archives and tmp logs", 1, 5, "2026-07-08 08:00:00")
        ])
    conn.commit()
    conn.close()

# Initialize DB on load
init_db()

# ----------------- UNIFIED STORAGE INTERFACE -----------------

def save_incident(incident_data: dict):
    """Saves or updates an incident ticket (OTS or SQLite)."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    incident_id = incident_data.get("id")
    
    # 1. Tablestore OTS write path
    if ots_client:
        try:
            from tablestore import Row, Condition, RowExistenceExpectation
            primary_key = [('id', incident_id)]
            attribute_columns = []
            for k, v in incident_data.items():
                if k != 'id' and v is not None:
                    # Convert types to string/int for OTS compatibility
                    val = int(v) if isinstance(v, bool) else v
                    attribute_columns.append((k, val))
            
            attribute_columns.append(('updated_at', now_str))
            if 'created_at' not in incident_data:
                attribute_columns.append(('created_at', now_str))
                
            ots_client.put_row('incidents', Row(primary_key, attribute_columns), Condition(RowExistenceExpectation.IGNORE))
            return
        except Exception as e:
            print(f"[OTS Save Error] Falling back to SQLite: {e}")

    # 2. SQLite local fallback path
    conn = get_sqlite_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM incidents WHERE id = ?", (incident_id,))
    exists = cursor.fetchone()
    
    if exists:
        # Update fields dynamically
        fields = []
        params = []
        for k, v in incident_data.items():
            if k != 'id' and v is not None:
                fields.append(f"{k} = ?")
                params.append(v)
        fields.append("updated_at = ?")
        params.append(now_str)
        params.append(incident_id)
        
        query = f"UPDATE incidents SET {', '.join(fields)} WHERE id = ?"
        cursor.execute(query, params)
    else:
        # Create ticket
        keys = ['id', 'created_at', 'updated_at']
        vals = [incident_id, now_str, now_str]
        for k, v in incident_data.items():
            if k != 'id' and v is not None:
                keys.append(k)
                vals.append(v)
                
        query = f"INSERT INTO incidents ({', '.join(keys)}) VALUES ({', '.join(['?'] * len(keys))})"
        cursor.execute(query, vals)
        
    conn.commit()
    conn.close()

def get_incident(incident_id: str) -> dict:
    """Retrieves an incident ticket."""
    if ots_client:
        try:
            primary_key = [('id', incident_id)]
            _, row, _ = ots_client.get_row('incidents', primary_key)
            if row:
                res = {'id': incident_id}
                for col_name, col_value, _ in row.attribute_columns:
                    res[col_name] = col_value
                return res
        except Exception as e:
            print(f"[OTS Read Error] {e}")

    conn = get_sqlite_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_incidents() -> list:
    """Returns all incidents ordered by creation time."""
    if ots_client:
        try:
            # Full scan of incidents (for Demo/Eval simplicity)
            from tablestore import Direction
            inclusive_start = [('id', '')]
            exclusive_end = [('id', 'zzzzzzzz')]
            _, _, rows, _ = ots_client.get_range('incidents', Direction.FORWARD, inclusive_start, exclusive_end)
            res = []
            for row in rows:
                item = {'id': row.primary_key[0][1]}
                for col_name, col_value, _ in row.attribute_columns:
                    item[col_name] = col_value
                res.append(item)
            return sorted(res, key=lambda x: x.get('created_at', ''), reverse=True)
        except Exception as e:
            print(f"[OTS Range Error] {e}")

    conn = get_sqlite_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM incidents ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def count_recent_alerts(service: str, hours: int = 24) -> int:
    """Queries how many alerts triggered on this service recently."""
    conn = get_sqlite_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM incidents 
        WHERE service = ? AND datetime(created_at) >= datetime('now', ?)
    """, (service, f"-{hours} hours"))
    cnt = cursor.fetchone()["cnt"]
    conn.close()
    return cnt

def get_kpi_metrics() -> dict:
    """Returns dynamic KPI metrics from database."""
    incidents = get_all_incidents()
    total = len(incidents)
    resolved = sum(1 for i in incidents if i.get('status') == 'resolved')
    failed = sum(1 for i in incidents if i.get('status') == 'failed')
    pending = sum(1 for i in incidents if i.get('status') == 'pending_approval')
    active = total - resolved - failed
    
    # Calculate rates
    success_rate = (resolved / (resolved + failed) * 100) if (resolved + failed) > 0 else 100.0
    auto_count = sum(1 for i in incidents if i.get('status') == 'resolved' and i.get('approved_by') == 'system-autopilot')
    auto_rate = (auto_count / resolved * 100) if resolved > 0 else 100.0
    
    # Avg resolution speed
    times = [int(i.get('resolution_time')) for i in incidents if i.get('resolution_time') and int(i.get('resolution_time')) > 0]
    avg_speed = (sum(times) / len(times)) if times else 0.0
    
    return {
        "total_alerts": total,
        "resolved_alerts": resolved,
        "active_alerts": active,
        "pending_approvals": pending,
        "success_rate": round(success_rate, 1),
        "auto_remediation_rate": round(auto_rate, 1),
        "avg_resolution_time": round(avg_speed, 1)
    }
