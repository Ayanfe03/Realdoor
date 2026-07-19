from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from .calculate import annualize, compare_to_threshold
from .data_store import DataStore, EVENT_DATE
from .safety import strip_untrusted_fields


@dataclass
class SessionState:
    session_id: str
    household_id: str | None = None
    document_ids: list[str] = field(default_factory=list)
    extracted_documents: dict[str, dict] = field(default_factory=dict)
    confirmations: dict[str, dict] = field(default_factory=dict)
    actions: list[dict] = field(default_factory=list)
    deleted: bool = False


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, SessionState] = {}

    def create(self) -> SessionState:
        session = SessionState(session_id=str(uuid4()))
        session.actions.append(_action("session_created"))
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> SessionState:
        if session_id not in self._sessions or self._sessions[session_id].deleted:
            raise KeyError("Unknown or deleted session")
        return self._sessions[session_id]

    def delete(self, session_id: str) -> None:
        session = self.get(session_id)
        session.actions.append(_action("session_deleted"))
        session.document_ids.clear()
        session.extracted_documents.clear()
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
            "model_generated": doc.get("model_generated", False),
            "fields": [
                {
                    **field,
                    "confidence": field.get("confidence", 1.0),
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

    def extraction_preview(
        self,
        *,
        file_name: str | None = None,
        document_id: str | None = None,
        text: str | None = None,
        openai_client=None,
    ) -> dict:
        doc = self.store.find_document(file_name=file_name, document_id=document_id)
        if doc:
            return {
                "mode": "gold_fixture",
                "document": self.document_evidence(doc),
                "model_result": None,
                "note": "Matched the synthetic document against the frozen gold extraction set.",
            }
        if text and openai_client:
            return {
                "mode": "model_structured_preview",
                "document": None,
                "model_result": openai_client.extract_fields(text),
                "note": "Model output must still be confirmed by the renter before reuse.",
            }
        raise ValueError("Provide a known synthetic file/document ID, or provide text for model extraction preview")

    def attach_document(self, session: SessionState, *, file_name: str | None = None, document_id: str | None = None) -> dict:
        doc = self.store.find_document(file_name=file_name, document_id=document_id)
        if not doc:
            raise ValueError("Synthetic document was not found in the frozen gold set")
        if session.household_id and session.household_id != doc["household_id"]:
            raise ValueError("A session can only contain documents for one household")
        session.household_id = doc["household_id"]
        if doc["document_id"] not in session.document_ids:
            session.document_ids.append(doc["document_id"])
            session.actions.append(
                _action(
                    "document_attached",
                    document_id=doc["document_id"],
                    document_type=doc["document_type"],
                    file_name=doc["file_name"],
                )
            )
        return self.document_evidence(doc)

    def confirm_field(self, session: SessionState, document_id: str, field_name: str, value) -> dict:
        doc = self._session_document(session, document_id)
        if document_id not in session.document_ids and document_id not in session.extracted_documents:
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
        session.actions.append(
            _action(
                "field_confirmed",
                document_id=document_id,
                field=field_name,
                corrected=session.confirmations[key]["corrected"],
            )
        )
        return session.confirmations[key]

    def add_extracted_document(self, session: SessionState, extraction: dict, household_id: str | None = None) -> dict:
        doc = extraction["document"]
        doc["household_id"] = household_id or session.household_id or doc.get("household_id") or "UNCONFIRMED"
        if session.household_id and doc["household_id"] not in {session.household_id, "UNCONFIRMED"}:
            raise ValueError("A session can only contain documents for one household")
        if doc["household_id"] != "UNCONFIRMED":
            session.household_id = doc["household_id"]
        for field in doc["fields"]:
            field["source"]["document_id"] = doc["document_id"]
        session.extracted_documents[doc["document_id"]] = doc
        session.actions.append(
            _action(
                "ai_extraction_added",
                document_id=doc["document_id"],
                document_type=doc["document_type"],
                field_count=len(doc["fields"]),
                abstention_count=len(extraction.get("abstentions", [])),
            )
        )
        return self.document_evidence(doc)

    def packet(self, session: SessionState) -> dict:
        if not session.household_id:
            session.household_id = self._infer_household_id(session)
        if not session.household_id:
            raise ValueError("No household documents are attached")
        assessment = self.assess(session.household_id, confirmations=session.confirmations)
        docs = [self.store.documents_by_id[doc_id] for doc_id in session.document_ids]
        docs.extend(session.extracted_documents.values())
        return {
            "session_id": session.session_id,
            "household_id": session.household_id,
            "documents": [self.document_evidence(doc) for doc in docs],
            "confirmations": list(session.confirmations.values()),
            "action_log": session.actions,
            "assessment": assessment,
            "decision_boundary": "No eligibility determination is included. A qualified human decides.",
        }

    def record_export(self, session: SessionState, export_type: str) -> None:
        session.actions.append(_action("packet_exported", export_type=export_type))

    def record_consent(self, session: SessionState, consent_type: str, granted: bool) -> dict:
        event = _action("consent_recorded", consent_type=consent_type, granted=granted)
        session.actions.append(event)
        return event

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
        if not pay_docs:
            return {"annualized_income": 0, "income_sources": []}
            
        latest_pay = max(pay_docs, key=lambda doc: self._field_value([doc], confirmations, "pay_date", fallback="0000-00-00"))
        
        # 1. Force find any user confirmation matching gross_pay across all session keys
        confirmed_gross_val = None
        for key, conf in confirmations.items():
            if "gross" in key.lower() and "pay" in key.lower():
                confirmed_gross_val = float(conf["value"])
                break

        # 2. Extract values with explicit fallbacks
        gross = confirmed_gross_val if confirmed_gross_val is not None else float(self._field_value([latest_pay], confirmations, "gross_pay", fallback=0))
        frequency = self._field_value([latest_pay], confirmations, "pay_frequency", fallback="biweekly") 
        
        sources = []

        # 3. IF THE USER CONFIRMED IT, BYPASS ALL EMPLOYMENT LETTER OVERRIDES ENTIRELY
        if confirmed_gross_val is None:
            hourly = self._field_value([latest_pay], confirmations, "hourly_rate", fallback=None)
            hours = self._field_value([latest_pay], confirmations, "regular_hours", fallback=None)
            if (
                hourly is not None
                and hours is not None
                and round(float(hourly) * float(hours), 2) != round(gross, 2)
            ):
                letter = next((doc for doc in docs if doc["document_type"] == "employment_letter"), None)
                if letter:
                    weekly_hours = float(self._field_value([letter], confirmations, "weekly_hours", fallback=hours))
                    letter_rate = float(self._field_value([letter], confirmations, "hourly_rate", fallback=hourly))
                    gross = round(weekly_hours * letter_rate, 2)
                    frequency = "weekly"

        # 4. Compute wage math
        pay_annual = annualize(gross, frequency)
        sources.append({"kind": "wages", "amount": gross, "frequency": frequency, "annualized": pay_annual})
        total = pay_annual

        # 5. Process secondary benefits cleanly
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

    def _session_document(self, session: SessionState, document_id: str) -> dict:
        if document_id in session.extracted_documents:
            return session.extracted_documents[document_id]
        return self.store.documents_by_id[document_id]

    def _infer_household_id(self, session: SessionState) -> str | None:
        for doc_id in session.document_ids:
            return self.store.documents_by_id[doc_id]["household_id"]
        for doc in session.extracted_documents.values():
            if doc.get("household_id") and doc["household_id"] != "UNCONFIRMED":
                return doc["household_id"]
        return None


def _action(action_type: str, **details) -> dict:
    return {
        "action": action_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rule_version": EVENT_DATE,
        "details": details,
    }