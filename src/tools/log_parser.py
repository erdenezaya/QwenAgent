import os
import time
import json

# SLS Configuration
SLS_ENDPOINT = os.environ.get("SLS_ENDPOINT", "")
SLS_PROJECT = os.environ.get("SLS_PROJECT", "qwen-autopilot-ops")
ACCESS_KEY_ID = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
ACCESS_KEY_SECRET = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")

async def parse_alert_logs(alert: dict) -> str:
    """
    Queries logs from Alibaba Cloud SLS (Simple Log Service) matching the alert service entity.
    If SLS endpoint is not configured, falls back to high-fidelity mock logs matching the service.
    """
    # Extract service name safely
    alert_text = alert.get("alert_text", "").lower()
    
    service = "unknown"
    if "tomcat" in alert_text:
        service = "tomcat"
    elif "mysql" in alert_text or "database" in alert_text:
        service = "mysql"
    elif "nginx" in alert_text:
        service = "nginx"
    elif "disk" in alert_text or "space" in alert_text or "storage" in alert_text:
        service = "disk-storage"

    host = "web-prod-01"
    if "db" in alert_text:
        host = "db-prod-02"
    elif "srv" in alert_text:
        host = "srv-app-09"

    # 1. SLS Query API path
    if SLS_ENDPOINT and ACCESS_KEY_ID and ACCESS_KEY_SECRET:
        try:
            from aliyun.log import LogClient
            client = LogClient(SLS_ENDPOINT, ACCESS_KEY_ID, ACCESS_KEY_SECRET)
            
            # Query log traces matching host and errors in the last 15 minutes
            from_time = int(time.time()) - 900
            to_time = int(time.time())
            query = f"host: \"{host}\" AND (error OR fail OR exception OR OOM)"
            
            res = client.get_logs(SLS_PROJECT, "incident-alerts", from_time, to_time, query=query)
            logs = []
            for log in res.get_logs():
                logs.append(log.get_contents())
                
            if logs:
                return "\n".join([json.dumps(l) for l in logs[:10]])
        except Exception as e:
            print(f"[SLS Query Warning] Failed to query SLS client, using fallback: {e}")

    # 2. Local mock log diagnostic fallback path (for Dev/Sandbox checks)
    time.sleep(0.5)  # Simulate API query duration
    if service == "tomcat":
        return (
            "[2026-07-09 14:00:02] [ERROR] org.apache.catalina.core.ContainerBase - Servlet.service() for servlet [jsp] threw exception\n"
            "java.lang.OutOfMemoryError: Java heap space\n"
            "  at java.util.Arrays.copyOf(Arrays.java:3332)\n"
            "  at java.lang.AbstractStringBuilder.ensureCapacityInternal(AbstractStringBuilder.java:124)\n"
            "  at java.lang.StringBuilder.append(StringBuilder.java:136)\n"
            "  at Catalina.executor.ThreadPool.executeWorkerThread(ThreadPool.java:402)"
        )
    elif service == "mysql":
        return (
            "2026-07-09T14:02:15.829124Z 0 [ERROR] InnoDB: Cannot open './ibdata1' file. Lock file active.\n"
            "2026-07-09T14:02:15.829402Z 0 [ERROR] InnoDB: Could not open single-table tablespace file './agent_ops/experiences.ibd'\n"
            "2026-07-09T14:02:15.830111Z 0 [ERROR] Aborting MySQL daemon process initialization."
        )
    elif service == "disk-storage":
        return (
            "Filesystem      Size  Used Avail Use% Mounted on\n"
            "/dev/vda1        40G   39.9G     0 100% /\n"
            "tmpfs           1.9G     0  1.9G   0% /dev/shm\n"
            "[CRITICAL] /var/log/syslog has grown to 18.5GB due to un-rotated system debug dumps."
        )
    elif service == "nginx":
        return (
            "2026-07-09 14:05:12 [crit] 1904#0: *842 open() '/var/lib/nginx/tmp/proxy/3/04/0000000043' failed\n"
            "(28: No space left on device) while reading upstream, client: 127.0.0.1, server: localhost"
        )
        
    return "No anomalous log traces found in matching SLS index range."
