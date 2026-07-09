import json
import re
from pathlib import Path

def load_allowed_commands():
    """Loads whitelisted commands config safely."""
    config_path = Path(__file__).parent.parent / "config" / "allowed_commands.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text())
        except Exception:
            pass
    return []

ALLOWED_COMMANDS = load_allowed_commands()

def validate_command(command: str) -> tuple[bool, str]:
    """
    Returns (is_safe, reason).
    Only permits exact matches or parameterized templates from allowed_commands.json.
    """
    cmd_stripped = command.strip()

    # Non-negotiable blacklist: block dangerous patterns regardless of allowlist matches
    BLOCK_PATTERNS = [
        r"\brm\s+-rf\b",
        r"\bmkfs\b",
        r"\bdd\s+if=",
        r">/dev/sd",
        r"\bchmod\s+777\b",
        r";\s*rm\b",
        r"\|\s*rm\b",
        r"&&\s*rm\b",
        r"\bwget\b",
        r"\bcurl\b"
    ]
    for pattern in BLOCK_PATTERNS:
        if re.search(pattern, cmd_stripped, re.IGNORECASE):
            return False, f"Blocked by safety policy: matches blacklisted pattern '{pattern}'"

    # Check against allowlist templates
    for template in ALLOWED_COMMANDS:
        # Convert template parameters to matching regex groups
        # E.g. "systemctl restart {service}" -> "systemctl\s+restart\s+\S+"
        escaped_template = re.escape(template)
        # re.escape converts "{param}" to "\{param\}"
        regex_pattern = re.sub(r'\\\{.*?\\\}', r'\\S+', escaped_template)
        # Normalize whitespace matching
        regex_pattern = regex_pattern.replace(r'\ ', r'\s+')
        
        if re.fullmatch(regex_pattern, cmd_stripped):
            return True, "Approved via allowlist"

    return False, f"Command not in allowlist: '{cmd_stripped}'"
