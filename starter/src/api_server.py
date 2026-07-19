from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .data_store import DataStore
from .export_service import ExportService
from .extraction_service import ExtractionService
from .openai_client import OpenAIClient
from .profile_service import ProfileService, SessionStore
from .rule_service import RuleService
from .safety import assess_request_safety


#  AFTER: (Forces data lookups to remain inside the starter root context)
ROOT = Path(__file__).resolve().parent.parent
DATA = DataStore(ROOT)
SESSIONS = SessionStore()
PROFILE = ProfileService(DATA)
OPENAI = OpenAIClient()
RULES = RuleService(DATA)
EXPORTS = ExportService()
EXTRACTION = ExtractionService()

app = FastAPI(
    title="RealDoor Application-Readiness API",
    description=(
        "Backend for the RealDoor copilot prototype. It extracts synthetic-document evidence, "
        "tracks renter confirmations, computes deterministic readiness outputs, and keeps final "
        "housing decisions out of scope."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ApiError(BaseModel):
    code: str = "bad_request"
    message: str


class ApiEnvelope(BaseModel):
    ok: bool
    data: Any = None
    error: ApiError | None = None


class AttachDocumentRequest(BaseModel):
    session_id: str
    file_name: str | None = Field(default=None, description="Synthetic PDF filename to match.")
    document_id: str | None = Field(default=None, description="Gold document ID to attach.")


class ConfirmFieldRequest(BaseModel):
    session_id: str
    document_id: str
    field: str
    value: Any


class SessionRequest(BaseModel):
    session_id: str


class ConsentRequest(BaseModel):
    session_id: str
    consent_type: str = Field(default="process_synthetic_document")
    granted: bool = True


class ExportRequest(BaseModel):
    session_id: str
    format: str = Field(default="json", pattern="^(json|html|pdf)$")


class CopilotRequest(BaseModel):
    message: str
    session_id: str | None = None


class ExtractionPreviewRequest(BaseModel):
    file_name: str | None = None
    document_id: str | None = None
    text: str | None = Field(default=None, description="Optional extracted document text for model extraction preview.")


class RuleQuestionRequest(BaseModel):
    question: str
    household_id: str | None = None


@app.exception_handler(Exception)
async def handle_exception(_request: Request, exc: Exception):
    return _error(str(exc), status_code=400)


@app.get("/api/health", response_model=ApiEnvelope, tags=["System"])
def health():
    return _ok({"openai_configured": OPENAI.configured, "model": OPENAI.model})


@app.get("/api/households", response_model=ApiEnvelope, tags=["Frozen Data"])
def list_households():
    return _ok({"households": DATA.list_households()})


@app.get("/api/documents/match", response_model=ApiEnvelope, tags=["Profile"])
def match_document(file_name: str):
    doc = DATA.find_document(file_name=file_name)
    return _ok({"document": PROFILE.document_evidence(doc) if doc else None})


@app.get("/api/households/assess", response_model=ApiEnvelope, tags=["Understand"])
def assess_household(household_id: str):
    return _ok(PROFILE.assess(household_id))


@app.post("/api/sessions", response_model=ApiEnvelope, tags=["Session"])
def create_session():
    session = SESSIONS.create()
    return _ok({"session_id": session.session_id})


@app.post("/api/sessions/attach-document", response_model=ApiEnvelope, tags=["Profile"])
def attach_document(payload: AttachDocumentRequest):
    session = SESSIONS.get(payload.session_id)
    evidence = PROFILE.attach_document(
        session,
        file_name=payload.file_name,
        document_id=payload.document_id,
    )
    return _ok({"session_id": session.session_id, "document": evidence})


@app.post("/api/sessions/confirm-field", response_model=ApiEnvelope, tags=["Profile"])
def confirm_field(payload: ConfirmFieldRequest):
    session = SESSIONS.get(payload.session_id)

    print("=== BEFORE CONFIRM ===")
    print("Current assessment:", PROFILE.packet(session)["assessment"]["annualized_income"])
    print("Income sources:", PROFILE.packet(session)["assessment"]["income_sources"])
    print("Confirming field:", payload.field, "with value:", payload.value)
    confirmation = PROFILE.confirm_field(session, payload.document_id, payload.field, payload.value)
    
    print("=== AFTER CONFIRM ===")
    packet = PROFILE.packet(session)
    print("New assessment:", packet["assessment"]["annualized_income"])
    print("Income sources:", packet["assessment"]["income_sources"])
    return _ok({"confirmation": confirmation, "assessment": packet["assessment"]})


@app.post("/api/sessions/packet", response_model=ApiEnvelope, tags=["Prepare"])
def packet(payload: SessionRequest):
    return _ok(PROFILE.packet(SESSIONS.get(payload.session_id)))


@app.post("/api/sessions/export", response_model=ApiEnvelope, tags=["Prepare"])
def export_packet(payload: SessionRequest):
    session = SESSIONS.get(payload.session_id)
    PROFILE.record_export(session, "json")
    return _ok(EXPORTS.packet_json(PROFILE.packet(session)))


@app.post("/api/sessions/export-file", tags=["Prepare"])
def export_packet_file(payload: ExportRequest):
    session = SESSIONS.get(payload.session_id)
    packet = PROFILE.packet(session)
    PROFILE.record_export(session, payload.format)
    if payload.format == "html":
        return Response(
            content=EXPORTS.packet_html(packet),
            media_type="text/html",
            headers={"Content-Disposition": "attachment; filename=realdoor-packet.html"},
        )
    if payload.format == "pdf":
        return Response(
            content=EXPORTS.packet_pdf(packet),
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=realdoor-packet.pdf"},
        )
    return JSONResponse(
        content=EXPORTS.packet_json(packet),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=realdoor-packet.json"},
    )


@app.post("/api/sessions/summary", response_model=ApiEnvelope, tags=["Prepare"])
def packet_summary(payload: SessionRequest):
    packet = PROFILE.packet(SESSIONS.get(payload.session_id))
    return _ok({"summary": OPENAI.packet_summary(packet), "packet": packet})


@app.post("/api/sessions/consent", response_model=ApiEnvelope, tags=["Session"])
def record_consent(payload: ConsentRequest):
    session = SESSIONS.get(payload.session_id)
    return _ok({"event": PROFILE.record_consent(session, payload.consent_type, payload.granted)})


@app.post("/api/sessions/delete", response_model=ApiEnvelope, tags=["Session"])
def delete_session(payload: SessionRequest):
    SESSIONS.delete(payload.session_id)
    return _ok({"deleted": True})


@app.post("/api/copilot", response_model=ApiEnvelope, tags=["Copilot"])
def copilot(payload: CopilotRequest):
    safety = assess_request_safety(payload.message)
    if not safety["allowed"]:
        return _ok({"safety": safety, "answer": safety["message"]})
    rule_answer = RULES.answer(payload.message, household_id=_session_household(payload.session_id))
    context = {"grounded_rule_answer": rule_answer}
    if payload.session_id:
        context["packet"] = PROFILE.packet(SESSIONS.get(payload.session_id))
    model_answer = OPENAI.grounded_answer(payload.message, context)
    return _ok({"safety": safety, "grounding": rule_answer, "answer": model_answer})


@app.post("/api/rules/answer", response_model=ApiEnvelope, tags=["Understand"])
def answer_rule_question(payload: RuleQuestionRequest):
    return _ok(RULES.answer(payload.question, household_id=payload.household_id))


@app.post("/api/extraction/preview", response_model=ApiEnvelope, tags=["Profile"])
def extraction_preview(payload: ExtractionPreviewRequest):
    doc = DATA.find_document(file_name=payload.file_name, document_id=payload.document_id)
    if doc:
        return _ok(PROFILE.extraction_preview(file_name=payload.file_name, document_id=payload.document_id))
    if payload.text:
        model_result = OPENAI.extract_fields(payload.text)
        return _ok(
            {
                "mode": "model_structured_preview",
                "model_result": model_result,
                "validated": EXTRACTION.validate_model_result(model_result),
                "note": "Validated fields must still be confirmed by the renter before reuse.",
            }
        )
    return _ok(
        PROFILE.extraction_preview(
            file_name=payload.file_name,
            document_id=payload.document_id,
            text=payload.text,
            openai_client=OPENAI,
        )
    )


@app.post("/api/extraction/upload", response_model=ApiEnvelope, tags=["Profile"])
async def upload_pdf_for_extraction(
    file: UploadFile = File(...),
    session_id: str | None = Form(default=None),
    household_id: str | None = Form(default=None),
    use_model: bool = Form(default=True),
):
    content = await file.read()
    session = SESSIONS.get(session_id) if session_id else None
    known_doc = DATA.find_document(file_name=file.filename)
    if known_doc:
        evidence = PROFILE.document_evidence(known_doc)
        attached = None
        if session:
            attached = PROFILE.attach_document(session, file_name=file.filename)
        return _ok(
            {
                "mode": "gold_fixture",
                "file_name": file.filename,
                "document": evidence,
                "attached_document": attached,
                "note": "Filename matched the frozen synthetic gold set; no model call was made.",
            }
        )
    extracted_text = EXTRACTION.text_from_pdf(content)
    model_result = OPENAI.extract_fields(extracted_text["text"]) if use_model else {"text": "", "fields": []}
    validated = EXTRACTION.validate_model_result(model_result, file_name=file.filename)
    attached = None
    if session and validated["status"] == "validated":
        attached = PROFILE.add_extracted_document(session, validated, household_id=household_id)
    return _ok(
        {
            "mode": "pdf_text_model_validation",
            "file_name": file.filename,
            "text": extracted_text,
            "model_result": model_result,
            "validated": validated,
            "attached_document": attached,
            "note": "Raw PDF text is returned for local review; do not persist raw document text outside the session boundary.",
        }
    )


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def _error(message: str, status_code: int = 400, code: str = "bad_request") -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "data": None, "error": {"code": code, "message": message}},
    )


def _session_household(session_id: str | None) -> str | None:
    if not session_id:
        return None
    try:
        return SESSIONS.get(session_id).household_id
    except KeyError:
        return None


def run(host: str = "127.0.0.1", port: int = 8000):
    uvicorn.run("src.api_server:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    run()
