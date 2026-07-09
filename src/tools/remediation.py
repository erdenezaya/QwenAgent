import time
from src.safety.allowlist import validate_command

async def execute_remediation(plan: dict) -> dict:
    """
    Executes the approved remediation command after validating it against the safety allowlist.
    """
    command = plan.get("command", "")

    # Enforce safety allowlist check
    is_safe, reason = validate_command(command)
    if not is_safe:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Safety Violation: {reason}",
            "status": "REJECTED_BY_SAFETY_GATE"
        }

    # Simulate command execution (In production, runs via audited SSH or Alibaba Cloud OOS)
    time.sleep(1.0)

    stdout = f"Command '{command}' executed successfully."
    if "restart" in command:
        stdout += f"\nService status: active (running) since {time.strftime('%Y-%m-%d %H:%M:%S')}"
    elif "delete" in command or "find" in command:
        stdout += "\nDeleted 43 stale log archives. Reclaimed 4.8 GB of disk storage space."
    elif "logrotate" in command:
        stdout += "\nLogrotate configuration applied successfully. Rotated Catalina log stream."

    return {
        "success": True,
        "stdout": stdout,
        "stderr": "",
        "status": "COMPLETED"
    }
