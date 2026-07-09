import unittest
from src.safety.allowlist import validate_command

class TestAllowlistEdgeCases(unittest.TestCase):
    def test_parameter_injections(self):
        """Verifies parameter injection attempts are correctly detected and rejected."""
        # Baseline safe command
        is_safe, _ = validate_command("find /var/log -name '*.log' -mtime +7 -delete")
        self.assertTrue(is_safe)

        # Injection attempts using semicolons or blacklisted commands
        is_safe, reason = validate_command("find /var/log; rm -rf / -name '*.log' -mtime +7 -delete")
        self.assertFalse(is_safe)
        self.assertIn("Blocked by safety policy", reason)

        # Injection attempts using pipes
        is_safe, reason = validate_command("find /var/log | rm -rf -name '*.log' -mtime +7 -delete")
        self.assertFalse(is_safe)
        self.assertIn("Blocked by safety policy", reason)

    def test_regex_matching_edge_cases(self):
        """Verifies multi-word parameter anomalies are blocked by exact regex match validation."""
        is_safe, reason = validate_command("systemctl restart tomcat apache2 mysql")
        self.assertFalse(is_safe)
        self.assertIn("not in allowlist", reason)

if __name__ == "__main__":
    unittest.main()
