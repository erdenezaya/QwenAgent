import time
import random

def restart_service(service_name: str, host: str) -> dict:
    """Restarts a system service (e.g., Tomcat, MySQL, Nginx) on a specific host."""
    service_name = service_name.lower().strip()
    host = host.strip()
    
    logs = [
        f"[{time.strftime('%H:%M:%S')}] Connecting to host {host} via SSH...",
        f"[{time.strftime('%H:%M:%S')}] Connection established. Executing: 'sudo systemctl restart {service_name}'",
        f"[{time.strftime('%H:%M:%S')}] Stopping service '{service_name}'...",
    ]
    time.sleep(1.0)
    
    # Simulate a potential failure scenario for demo purposes
    if service_name == "mysql" and "db-prod" in host.lower() and random.random() < 0.2:
        logs.append(f"[{time.strftime('%H:%M:%S')}] Error: MySQL failed to stop. PID lockfile exists.")
        logs.append(f"[{time.strftime('%H:%M:%S')}] Failed to restart MySQL service.")
        return {
            "success": False,
            "message": f"Failed to restart service {service_name} on {host}",
            "logs": "\n".join(logs)
        }
        
    logs.append(f"[{time.strftime('%H:%M:%S')}] Service stopped successfully.")
    logs.append(f"[{time.strftime('%H:%M:%S')}] Starting service '{service_name}'...")
    time.sleep(1.5)
    logs.append(f"[{time.strftime('%H:%M:%S')}] Service '{service_name}' is running. PID: {random.randint(1000, 9999)}")
    logs.append(f"[{time.strftime('%H:%M:%S')}] Verifying service status via systemctl... Status: ACTIVE (running)")
    
    return {
        "success": True,
        "message": f"Service {service_name} restarted successfully on {host}",
        "logs": "\n".join(logs)
    }

def clear_disk_space(path: str, host: str, file_pattern: str = "*.log") -> dict:
    """Clears temporary files or log archives to free up disk space in a directory."""
    path = path.strip()
    host = host.strip()
    
    logs = [
        f"[{time.strftime('%H:%M:%S')}] SSH connection to {host} opened.",
        f"[{time.strftime('%H:%M:%S')}] Scanning directory '{path}' for files matching '{file_pattern}'...",
    ]
    time.sleep(0.8)
    
    # Mocking files cleared
    if "log" in file_pattern or "tmp" in path:
        freed = random.randint(120, 850) # MB
        files_deleted = [
            f"{path}/system-2026-07-04.log.gz",
            f"{path}/debug-stdout-2026-07-05.log",
            f"{path}/access-nginx-2026-07-06.log.tmp",
            f"{path}/gc-daemon.log"
        ]
        for f in files_deleted:
            logs.append(f"[{time.strftime('%H:%M:%S')}] Deleted file: {f}")
        logs.append(f"[{time.strftime('%H:%M:%S')}] Disk cleanup completed. Total space freed: {freed} MB.")
        return {
            "success": True,
            "message": f"Freed {freed} MB on {host} in directory {path}",
            "logs": "\n".join(logs),
            "freed_mb": freed
        }
    else:
        logs.append(f"[{time.strftime('%H:%M:%S')}] WARNING: Specified pattern '{file_pattern}' did not match any safe-to-delete temporary files.")
        logs.append(f"[{time.strftime('%H:%M:%S')}] No files deleted.")
        return {
            "success": False,
            "message": f"No files cleared on {host} under path {path} with pattern {file_pattern}",
            "logs": "\n".join(logs),
            "freed_mb": 0
        }

def scale_kubernetes_deployment(deployment_name: str, namespace: str, replicas: int) -> dict:
    """Scales a Kubernetes deployment replica count to handle high load or scale down."""
    deployment_name = deployment_name.lower().strip()
    namespace = namespace.lower().strip()
    
    logs = [
        f"[{time.strftime('%H:%M:%S')}] Initializing kubectl client connection...",
        f"[{time.strftime('%H:%M:%S')}] Connected to Kubernetes Cluster. Namespace: {namespace}.",
        f"[{time.strftime('%H:%M:%S')}] Running: 'kubectl scale deployment/{deployment_name} --replicas={replicas} -n {namespace}'",
    ]
    time.sleep(1.2)
    
    logs.append(f"[{time.strftime('%H:%M:%S')}] Scaling request sent. Scaling deployment '{deployment_name}' to {replicas} replicas.")
    logs.append(f"[{time.strftime('%H:%M:%S')}] Waiting for replica rollout to complete...")
    time.sleep(1.5)
    logs.append(f"[{time.strftime('%H:%M:%S')}] Rollout status: {replicas}/{replicas} replicas updated and available.")
    logs.append(f"[{time.strftime('%H:%M:%S')}] Event: Deployment scaling completed successfully.")
    
    return {
        "success": True,
        "message": f"Deployment {deployment_name} in namespace {namespace} scaled to {replicas} replicas",
        "logs": "\n".join(logs)
    }

def check_service_health(service_name: str, host: str) -> dict:
    """Checks the health, CPU load, and port availability of a service on a host."""
    service_name = service_name.lower().strip()
    host = host.strip()
    
    logs = [
        f"[{time.strftime('%H:%M:%S')}] Querying health status of service '{service_name}' on host {host}...",
    ]
    time.sleep(0.5)
    
    # Mocking status check
    ports = {"tomcat": 8080, "mysql": 3306, "nginx": 80}
    port = ports.get(service_name, 80)
    
    logs.append(f"[{time.strftime('%H:%M:%S')}] Checking local port TCP/{port} binding... Active.")
    logs.append(f"[{time.strftime('%H:%M:%S')}] Service process status: RUNNING")
    
    cpu = random.randint(5, 25) # CPU usage after remediation
    mem = random.randint(200, 600) # MB
    
    logs.append(f"[{time.strftime('%H:%M:%S')}] Resource utilization: CPU: {cpu}%, RAM: {mem}MB")
    logs.append(f"[{time.strftime('%H:%M:%S')}] HTTP Health Check Endpoint '/health': 200 OK")
    
    return {
        "success": True,
        "message": f"Service {service_name} on {host} is healthy. CPU: {cpu}%, RAM: {mem}MB",
        "logs": "\n".join(logs),
        "metrics": {"cpu_percent": cpu, "memory_mb": mem}
    }

def fetch_service_logs(service_name: str, host: str) -> dict:
    """Fetches the last 50 lines of system/application logs from a host for diagnostics."""
    service_name = service_name.lower().strip()
    host = host.strip()
    
    logs = [
        f"[{time.strftime('%H:%M:%S')}] Connecting to SSH agent at {host}...",
        f"[{time.strftime('%H:%M:%S')}] Connection successful. Reading service output logs for '{service_name}'...",
    ]
    
    if service_name == "tomcat":
        log_content = (
            "2026-07-08 21:28:10.512 ERROR [http-nio-8080-exec-12] org.apache.tomcat.util.net.NioEndpoint$SocketProcessor.doRun: \n"
            "  java.lang.OutOfMemoryError: Java heap space\n"
            "  at java.util.concurrent.locks.AbstractQueuedSynchronizer$ConditionObject.await(AbstractQueuedSynchronizer.java:2039)\n"
            "  at java.util.LinkedQueue.take(LinkedQueue.java:83)\n"
            "  at org.apache.tomcat.util.threads.TaskQueue.take(TaskQueue.java:100)\n"
            "  at org.apache.tomcat.util.threads.ThreadPoolExecutor.getTask(ThreadPoolExecutor.java:1061)\n"
            "  at org.apache.tomcat.util.threads.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1121)\n"
            "2026-07-08 21:28:15.820 WARNING [ContainerBackgroundProcessor] org.apache.catalina.valves.StuckThreadDetectionValve.notifyStuckThreadCompleted: \n"
            "  Thread http-nio-8080-exec-12 has been active for 120 seconds and is suspected of being stuck."
        )
    elif service_name == "mysql":
        log_content = (
            "2026-07-08T21:29:05.124840Z 0 [System] [MY-010116] [Server] /usr/sbin/mysqld (mysqld 8.0.28) starting as process 4120...\n"
            "2026-07-08T21:29:10.601920Z 0 [ERROR] [MY-012592] [InnoDB] InnoDB: Table flags are corrupt. Connection limits reached.\n"
            "2026-07-08T21:29:10.602210Z 0 [ERROR] [MY-010202] [Server] Plugin 'InnoDB' init function returned error.\n"
            "2026-07-08T21:29:10.602300Z 0 [ERROR] [MY-010119] [Server] Aborting connection (too many open files or lock timeout).\n"
            "2026-07-08T21:29:11.850940Z 0 [System] [MY-010910] [Server] /usr/sbin/mysqld: Shutdown complete."
        )
    elif service_name == "nginx":
        log_content = (
            "2026/07/08 21:28:01 [error] 14092#14092: *4912 upstream timed out (110: Connection timed out) while reading response header from upstream, client: 192.168.1.45, server: app.io\n"
            "2026/07/08 21:28:10 [crit] 14092#14092: *4955 open() \"/var/lib/nginx/tmp/proxy/5/03/0000000035\" failed (28: No space left on device) while reading upstream, client: 192.168.1.104, server: app.io"
        )
    elif service_name == "disk-storage":
        log_content = (
            "Filesystem      Size  Used Avail Use% Mounted on\n"
            "/dev/xvda1       40G   39.7G     0.1G 99.8% /\n"
            "du: cannot access '/var/log/journal/1283081a/': No space left on device\n"
            "systemd-journald[392]: Failed to write entry (23 items, 684B), ignoring: No space left on device"
        )
    else:
        log_content = f"Log Buffer Empty for service '{service_name}' on {host}. Status: UNRESPONSIVE"
        
    logs.append("--- Service Log Output ---")
    logs.append(log_content)
    
    return {
        "success": True,
        "message": f"Successfully fetched logs for {service_name} on {host}",
        "logs": "\n".join(logs),
        "log_content": log_content
    }

# Tool registration metadata for Qwen functions/tools calling
TOOLS_METADATA = [
    {
        "type": "function",
        "function": {
            "name": "fetch_service_logs",
            "description": "Fetches the last 50 lines of system/application logs from a host for diagnostics and root cause analysis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": "The name of the service, e.g. 'tomcat', 'mysql', 'nginx'."
                    },
                    "host": {
                        "type": "string",
                        "description": "The target host or server name."
                    }
                },
                "required": ["service_name", "host"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "restart_service",
            "description": "Restarts a system service (e.g. tomcat, mysql, nginx, apache) on a specific host using systemctl.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": "The name of the service to restart, e.g. 'tomcat', 'mysql'."
                    },
                    "host": {
                        "type": "string",
                        "description": "The target host or server name, e.g. 'web-server-01', 'db-prod-02'."
                    }
                },
                "required": ["service_name", "host"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_disk_space",
            "description": "Clears temporary log or file archives to free up disk space in a designated directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The absolute file path directory to clean up, e.g. '/var/log/nginx', '/tmp'."
                    },
                    "host": {
                        "type": "string",
                        "description": "The target host or server name."
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "The file extension or pattern to target. Defaults to '*.log'. Use '*.log' or '*.tmp' for safety.",
                        "default": "*.log"
                    }
                },
                "required": ["path", "host"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scale_kubernetes_deployment",
            "description": "Scales a Kubernetes deployment's replica count in a specified namespace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deployment_name": {
                        "type": "string",
                        "description": "The deployment name, e.g. 'api-gateway', 'payment-service'."
                    },
                    "namespace": {
                        "type": "string",
                        "description": "The Kubernetes namespace, e.g. 'production', 'staging'."
                    },
                    "replicas": {
                        "type": "integer",
                        "description": "The target number of replicas (instances) to scale to."
                    }
                },
                "required": ["deployment_name", "namespace", "replicas"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_service_health",
            "description": "Performs a system status check to verify a service is healthy and query its current CPU/RAM metrics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": "The name of the service to check, e.g. 'tomcat', 'mysql'."
                    },
                    "host": {
                        "type": "string",
                        "description": "The target host or server name."
                    }
                },
                "required": ["service_name", "host"]
            }
        }
    }
]

def execute_tool(name: str, arguments: dict) -> dict:
    """Executes a tool by name and arguments, catching exceptions."""
    try:
        if name == "fetch_service_logs":
            return fetch_service_logs(arguments["service_name"], arguments["host"])
        elif name == "restart_service":
            return restart_service(arguments["service_name"], arguments["host"])
        elif name == "clear_disk_space":
            return clear_disk_space(
                arguments["path"], 
                arguments["host"], 
                arguments.get("file_pattern", "*.log")
            )
        elif name == "scale_kubernetes_deployment":
            return scale_kubernetes_deployment(
                arguments["deployment_name"], 
                arguments["namespace"], 
                arguments["replicas"]
            )
        elif name == "check_service_health":
            return check_service_health(arguments["service_name"], arguments["host"])
        else:
            return {
                "success": False,
                "message": f"Tool '{name}' not found",
                "logs": f"Error: Tool '{name}' is not registered."
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Execution error in tool '{name}': {str(e)}",
            "logs": f"Error: {str(e)}"
        }
