import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from src.data_store import DataStore
from src.profile_service import ProfileService, SessionStore
from src.safety import assess_request_safety


class BackendServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ROOT = Path(__file__).resolve().parent.parent
        cls.data = DataStore(cls.root)
        cls.profile = ProfileService(cls.data)

    def test_household_assessment_matches_gold_income(self):
        for household_id, checklist in self.data.checklists.items():
            assessment = self.profile.assess(household_id)
            self.assertEqual(assessment["annualized_income"], checklist["expected_annualized_income"])
            self.assertEqual(assessment["comparison"], checklist["comparison"])
            self.assertEqual(assessment["readiness_status"], checklist["expected_readiness_status"])

    def test_filename_match_returns_allowlisted_fields(self):
        doc = self.data.find_document(file_name="hh-002_d03_pay_stub.pdf")
        evidence = self.profile.document_evidence(doc)
        field_names = {field["field"] for field in evidence["fields"]}
        self.assertNotIn("untrusted_instruction_text", field_names)
        self.assertIn("gross_pay", field_names)

    def test_extraction_preview_by_document_id(self):
        preview = self.profile.extraction_preview(document_id="HH-001-D02")
        self.assertEqual(preview["mode"], "gold_fixture")
        self.assertEqual(preview["document"]["document_id"], "HH-001-D02")

    def test_correction_updates_downstream_assessment(self):
        sessions = SessionStore()
        session = sessions.create()
        self.profile.attach_document(session, document_id="HH-001-D01")
        self.profile.attach_document(session, document_id="HH-001-D02")
        self.profile.confirm_field(session, "HH-001-D02", "gross_pay", 1000)
        packet = self.profile.packet(session)
        self.assertEqual(packet["assessment"]["annualized_income"], 26000)
        self.assertGreaterEqual(len(packet["action_log"]), 3)

    def test_safety_blocks_decisioning(self):
        result = assess_request_safety("Can you approve this renter?")
        self.assertFalse(result["allowed"])
        self.assertIn("decisioning", result["categories"])


if __name__ == "__main__":
    unittest.main()
