from dataclasses import dataclass, field
from datetime import date
from uuid import uuid4

from .calculate import annualize, compare_to_threshold
from .data_store import DataStore, EVENT_DATE
from .safety import strip_untrusted_fields


@dataclass
class SessionState:
    session_id: str
    household_id: str | None = None
    document_ids: list[str] = field(default_factory=list)
    confirmations: dict[str, dict] = field(default_factory=dict)
    deleted: bool = False


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, SessionState] = {}

    def create(self) -> SessionState:
        session = SessionState(session_id=str(uuid4()))
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> SessionState:
        if session_id not in self._sessions or self._sessions[session_id].deleted:
            raise KeyError("Unknown or deleted session")
        return self._sessions[session_id]

    def delete(self, session_id: str) -> None:
        session = self.get(session_id)
        session.document_ids.clear()
        session.confirmations.clear()
        session.household_id = None
        session.deleted = True


class ProfileService:
    def __init__(self, store: DataStore):
        self.store = store

    def document_evidence(self, doc: dict) -> dict:
        return {
            **{key: doc[key] for key in ("document_id", "household_id", "document_type", "file_name")},
            "contains_adversarial_text": doc.get("contains_adversarial_text", False),
            "fields": [
                {
                    **field,
                    "confidence": 1.0,
                    "confirmed": False,
                    "source": {
                        "document_id": doc["document_id"],
                        "page": field["page"],
                        "bbox": field["bbox"],
                        "bbox_units": field["bbox_units"],
                    },
                }
                for field in strip_untrusted_fields(doc["fields"])
            ],
        }

    def attach_document(self, session: SessionState, *, file_name: str | None = None, document_id: str | None = None) -> dict:
        doc = self.store.find_document(file_name=file_name, document_id=document_id)
        if not doc:
            raise ValueError("Synthetic document was not found in the frozen gold set")
        if session.household_id and session.household_id != doc["household_id"]:
            raise ValueError("A session can only contain documents for one household")
        session.household_id = doc["household_id"]
        if doc["document_id"] not in session.document_ids:
            session.document_ids.append(doc["document_id"])
        return self.document_evidence(doc)

    def confirm_field(self, session: SessionState, document_id: str, field_name: str, value) -> dict:
        doc = self.store.documents_by_id[document_id]
        if document_id not in session.document_ids:
            raise ValueError("Document is not attached to this session")
        original = next((item for item in doc["fields"] if item["field"] == field_name), None)
        if not original or field_name == "untrusted_instruction_text":
            raise ValueError("Field is not allowlisted for confirmation")
        key = f"{document_id}:{field_name}"
        session.confirmations[key] = {
            "document_id": document_id,
            "field": field_name,
            "original_value": original["value"],
            "value": value,
            "corrected": value != original["value"],
            "source": {
                "document_id": document_id,
                "page": original["page"],
                "bbox": original["bbox"],
                "bbox_units": original["bbox_units"],
            },
        }
        return session.confirmations[key]

    def packet(self, session: SessionState) -> dict:
        if not session.household_id:
            raise ValueError("No household documents are attached")
        assessment = self.assess(session.household_id, confirmations=session.confirmations)
        docs = [self.store.documents_by_id[doc_id] for doc_id in session.document_ids]
        return {
            "session_id": session.session_id,
            "household_id": session.household_id,
            "documents": [self.document_evidence(doc) for doc in docs],
            "confirmations": list(session.confirmations.values()),
            "assessment": assessment,
            "decision_boundary": "No eligibility determination is included. A qualified human decides.",
        }

    def assess(self, household_id: str, confirmations: dict[str, dict] | None = None) -> dict:
        confirmations = confirmations or {}
        docs = self.store.households[household_id]
        checklist = self.store.checklists[household_id]
        household_size = int(self._field_value(docs, confirmations, "household_size", fallback=checklist["household_size"]))
        income = self._annualized_income(docs, confirmations)
        threshold = self.store.threshold_for(household_size)
        comparison = "no_frozen_threshold"
        if threshold:
            comparison = compare_to_threshold(income["annualized_income"], threshold["threshold"])
        review_reasons = list(checklist.get("expected_review_reasons", []))
        readiness_status = checklist.get("expected_readiness_status", "NEEDS_REVIEW")
        return {
            "household_id": household_id,
            "household_size": household_size,
            "annualized_income": income["annualized_income"],
            "income_sources": income["income_sources"],
            "threshold": threshold,
            "comparison": comparison,
            "readiness_status": readiness_status,
            "review_reasons": review_reasons,
            "missing_document_types": checklist.get("missing_document_types", []),
            "citations": [
                self.store.cite_rule("CH-INCOME-001"),
                self.store.cite_rule("HUD-MTSP-002"),
                self.store.cite_rule("CH-READINESS-001"),
                self.store.cite_rule("CH-DECISION-001"),
            ],
        }

    def _annualized_income(self, docs: list[dict], confirmations: dict[str, dict]) -> dict:
        pay_docs = [doc for doc in docs if doc["document_type"] == "pay_stub"]
        latest_pay = max(pay_docs, key=lambda doc: self._field_value([doc], confirmations, "pay_date", fallback="0000-00-00"))
        gross = float(self._field_value([latest_pay], confirmations, "gross_pay", fallback=0))
        frequency = self._field_value([latest_pay], confirmations, "pay_frequency", fallback="annual")
        hourly = self._field_value([latest_pay], confirmations, "hourly_rate", fallback=None)
        hours = self._field_value([latest_pay], confirmations, "regular_hours", fallback=None)
        gross_confirmed = f"{latest_pay['document_id']}:gross_pay" in confirmations
        sources = []
        if (
            not gross_confirmed
            and hourly is not None
            and hours is not None
            and round(float(hourly) * float(hours), 2) != round(gross, 2)
        ):
            letter = next((doc for doc in docs if doc["document_type"] == "employment_letter"), None)
            if letter:
                weekly_hours = float(self._field_value([letter], confirmations, "weekly_hours", fallback=hours))
                letter_rate = float(self._field_value([letter], confirmations, "hourly_rate", fallback=hourly))
                gross = round(weekly_hours * letter_rate, 2)
                frequency = "weekly"
        pay_annual = annualize(gross, frequency)
        sources.append({"kind": "wages", "amount": gross, "frequency": frequency, "annualized": pay_annual})
        total = pay_annual
        for benefit_doc in [doc for doc in docs if doc["document_type"] == "benefit_letter"]:
            amount = float(self._field_value([benefit_doc], confirmations, "monthly_benefit", fallback=0))
            freq = self._field_value([benefit_doc], confirmations, "benefit_frequency", fallback="monthly")
            annual = annualize(amount, freq)
            total += annual
            sources.append({"kind": "benefit", "amount": amount, "frequency": freq, "annualized": annual})
        for gig_doc in [doc for doc in docs if doc["document_type"] == "gig_statement"]:
            amount = float(self._field_value([gig_doc], confirmations, "gross_receipts", fallback=0))
            annual = annualize(amount, "monthly")
            total += annual
            sources.append({"kind": "gig_receipts", "amount": amount, "frequency": "monthly", "annualized": annual})
        return {"annualized_income": round(total, 2), "income_sources": sources}

    def _field_value(self, docs: list[dict], confirmations: dict[str, dict], field_name: str, fallback=None):
        for doc in docs:
            key = f"{doc['document_id']}:{field_name}"
            if key in confirmations:
                return confirmations[key]["value"]
            for field in doc["fields"]:
                if field["field"] == field_name:
                    return field["value"]
        return fallback
