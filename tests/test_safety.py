import unittest
from src.safety.allowlist import validate_command

class TestSafetyAllowlist(unittest.TestCase):
    def test_allowlisted_commands(self):
        """Verifies whitelisted command patterns successfully pass safety checks."""
        is_safe, reason = validate_command("systemctl restart tomcat")
        self.assertTrue(is_safe, f"Failed: {reason}")
        
        is_safe, reason = validate_command("df -h /var/log")
        self.assertTrue(is_safe, f"Failed: {reason}")

    def test_non_allowlisted_commands(self):
        """Verifies non-whitelisted templates are blocked."""
        is_safe, reason = validate_command("apt-get update")
        self.assertFalse(is_safe)
        self.assertIn("not in allowlist", reason)

    def test_malicious_command_injections(self):
        """Verifies malicious command chains and blacklisted sequences are caught."""
        is_safe, reason = validate_command("systemctl restart tomcat; rm -rf /")
        self.assertFalse(is_safe)
        self.assertIn("Blocked by safety policy", reason)
        
        is_safe, reason = validate_command("chmod 777 /etc/passwd")
        self.assertFalse(is_safe)
        self.assertIn("Blocked by safety policy", reason)

if __name__ == "__main__":
    unittest.main()
