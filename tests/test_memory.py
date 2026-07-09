import unittest
import uuid
from src import memory

class TestMemoryStorage(unittest.TestCase):
    def test_save_and_retrieve_incident(self):
        """Verifies that incident records can be successfully written and retrieved."""
        incident_id = str(uuid.uuid4())[:8]
        ticket = {
            "id": incident_id,
            "raw_alert": "PROMETHEUS: Database connection refused on host db-prod-02",
            "status": "triage",
            "service": "mysql",
            "host": "db-prod-02"
        }

        memory.save_incident(ticket)
        retrieved = memory.get_incident(incident_id)

        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.get("id"), incident_id)
        self.assertEqual(retrieved.get("status"), "triage")
        self.assertEqual(retrieved.get("service"), "mysql")

    def test_update_incident_state(self):
        """Verifies state transition updates write cleanly."""
        incident_id = str(uuid.uuid4())[:8]
        ticket = {
            "id": incident_id,
            "raw_alert": "Disk usage threshold crossed on app node",
            "status": "triage"
        }
        memory.save_incident(ticket)

        # Transition status to resolved with metrics
        memory.save_incident({
            "id": incident_id,
            "status": "resolved",
            "resolution_time": 10
        })

        retrieved = memory.get_incident(incident_id)
        self.assertEqual(retrieved.get("status"), "resolved")
        self.assertEqual(int(retrieved.get("resolution_time")), 10)

if __name__ == "__main__":
    unittest.main()
