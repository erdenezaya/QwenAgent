def score_blast_radius(plan: dict) -> float:
    """
    Evaluates the blast radius of a proposed remediation plan.
    Returns a score between 0.0 (no risk) and 1.0 (critical system risk).
    If score >= 0.7, manual Operator Approval is mandated.
    """
    command = plan.get("command", "").strip().lower()

    # 1. High Risk: Service restarts or container terminations (Potential Downtime)
    if "restart" in command or "reboot" in command:
        if "mysql" in command or "db-" in command:
            return 0.9  # Critical database risk
        if "nginx" in command or "tomcat" in command:
            return 0.75 # Web tier restart risk
        return 0.7

    # 2. Medium Risk: File deletions, cache purging
    if "delete" in command or "-delete" in command or "rm " in command:
        return 0.5
    if "logrotate" in command:
        return 0.4

    # 3. Low Risk: Read-only diagnostics
    if "df " in command or "du " in command or "journalctl" in command or "status" in command:
        return 0.1

    return 0.3  # Default fallback score
