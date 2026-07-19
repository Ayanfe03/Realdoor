import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from src.api_server import app


class ApiServerTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_envelope(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertIn("model", body["data"])

    def test_legacy_routes_are_not_registered(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 404)

    def test_assess_household(self):
        response = self.client.get("/api/households/assess", params={"household_id": "HH-001"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["annualized_income"], 56316.0)
        self.assertEqual(body["data"]["comparison"], "below_or_equal")

    def test_session_confirm_packet_flow(self):
        session_id = self.client.post("/api/sessions").json()["data"]["session_id"]
        attach = self.client.post(
            "/api/sessions/attach-document",
            json={"session_id": session_id, "document_id": "HH-001-D02"},
        )
        self.assertTrue(attach.json()["ok"])
        confirm = self.client.post(
            "/api/sessions/confirm-field",
            json={"session_id": session_id, "document_id": "HH-001-D02", "field": "gross_pay", "value": 1000},
        )
        self.assertTrue(confirm.json()["ok"])
        self.assertEqual(confirm.json()["data"]["assessment"]["annualized_income"], 26000)
        packet = self.client.post("/api/sessions/packet", json={"session_id": session_id})
        self.assertTrue(packet.json()["ok"])
        self.assertEqual(packet.json()["data"]["household_id"], "HH-001")
        self.assertGreaterEqual(len(packet.json()["data"]["action_log"]), 3)

    def test_copilot_refusal_avoids_model_call(self):
        response = self.client.post("/api/copilot", json={"message": "Can you approve this renter?"})
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["data"]["safety"]["allowed"])

    def test_rules_answer_is_grounded(self):
        response = self.client.post(
            "/api/rules/answer",
            json={"question": "What is the 60% threshold?", "household_id": "HH-001"},
        )
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["status"], "grounded")
        self.assertIn("citations", body["data"])
        self.assertGreaterEqual(len(body["data"]["qa_matches"]), 1)

    def test_extraction_preview_uses_gold_fixture(self):
        response = self.client.post("/api/extraction/preview", json={"document_id": "HH-001-D02"})
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["mode"], "gold_fixture")
        self.assertEqual(body["data"]["document"]["document_id"], "HH-001-D02")

    def test_export_packet(self):
        session_id = self.client.post("/api/sessions").json()["data"]["session_id"]
        self.client.post(
            "/api/sessions/attach-document",
            json={"session_id": session_id, "document_id": "HH-001-D02"},
        )
        response = self.client.post("/api/sessions/export", json={"session_id": session_id})
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["export_type"], "realdoor_application_readiness_packet")
        self.assertEqual(body["data"]["packet"]["household_id"], "HH-001")

    def test_export_packet_file_html(self):
        session_id = self.client.post("/api/sessions").json()["data"]["session_id"]
        self.client.post(
            "/api/sessions/attach-document",
            json={"session_id": session_id, "document_id": "HH-001-D02"},
        )
        response = self.client.post("/api/sessions/export-file", json={"session_id": session_id, "format": "html"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("RealDoor Application-Readiness Packet", response.text)

    def test_export_packet_file_pdf(self):
        session_id = self.client.post("/api/sessions").json()["data"]["session_id"]
        self.client.post(
            "/api/sessions/attach-document",
            json={"session_id": session_id, "document_id": "HH-001-D02"},
        )
        response = self.client.post("/api/sessions/export-file", json={"session_id": session_id, "format": "pdf"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/pdf", response.headers["content-type"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_packet_summary_uses_openai_boundary(self):
        session_id = self.client.post("/api/sessions").json()["data"]["session_id"]
        self.client.post(
            "/api/sessions/attach-document",
            json={"session_id": session_id, "document_id": "HH-001-D02"},
        )
        with patch("src.api_server.OPENAI.packet_summary") as packet_summary:
            packet_summary.return_value = {"status": "summarized", "summary": "Ready for review, not a decision."}
            response = self.client.post("/api/sessions/summary", json={"session_id": session_id})
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["summary"]["status"], "summarized")

    def test_consent_event(self):
        session_id = self.client.post("/api/sessions").json()["data"]["session_id"]
        response = self.client.post(
            "/api/sessions/consent",
            json={"session_id": session_id, "consent_type": "process_synthetic_document", "granted": True},
        )
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["event"]["action"], "consent_recorded")

    def test_upload_known_synthetic_pdf_uses_gold_without_model(self):
        session_id = self.client.post("/api/sessions").json()["data"]["session_id"]
        pdf_path = Path(__file__).resolve().parent.parent / "synthetic_documents" / "documents" / "hh-001_d02_pay_stub.pdf"
        with pdf_path.open("rb") as f:
            response = self.client.post(
                "/api/extraction/upload",
                data={"session_id": session_id},
                files={"file": ("hh-001_d02_pay_stub.pdf", f, "application/pdf")},
            )
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["mode"], "gold_fixture")
        self.assertEqual(body["data"]["document"]["document_id"], "HH-001-D02")


if __name__ == "__main__":
    unittest.main()
