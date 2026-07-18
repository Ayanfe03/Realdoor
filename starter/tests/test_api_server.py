import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from fastapi.testclient import TestClient

from src.api_server import app


class ApiServerTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_envelope(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertIn("model", body["data"])

    def test_assess_household(self):
        response = self.client.get("/households/assess", params={"household_id": "HH-001"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["annualized_income"], 56316.0)
        self.assertEqual(body["data"]["comparison"], "below_or_equal")

    def test_session_confirm_packet_flow(self):
        session_id = self.client.post("/sessions").json()["data"]["session_id"]
        attach = self.client.post(
            "/sessions/attach-document",
            json={"session_id": session_id, "document_id": "HH-001-D02"},
        )
        self.assertTrue(attach.json()["ok"])
        confirm = self.client.post(
            "/sessions/confirm-field",
            json={"session_id": session_id, "document_id": "HH-001-D02", "field": "gross_pay", "value": 1000},
        )
        self.assertTrue(confirm.json()["ok"])
        self.assertEqual(confirm.json()["data"]["assessment"]["annualized_income"], 26000)
        packet = self.client.post("/sessions/packet", json={"session_id": session_id})
        self.assertTrue(packet.json()["ok"])
        self.assertEqual(packet.json()["data"]["household_id"], "HH-001")

    def test_copilot_refusal_avoids_model_call(self):
        response = self.client.post("/copilot", json={"message": "Can you approve this renter?"})
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["data"]["safety"]["allowed"])


if __name__ == "__main__":
    unittest.main()
