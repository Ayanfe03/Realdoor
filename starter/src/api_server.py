from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .data_store import DataStore
from .openai_client import OpenAIClient
from .profile_service import ProfileService, SessionStore
from .safety import assess_request_safety


ROOT = Path(__file__).parents[2]
DATA = DataStore(ROOT)
SESSIONS = SessionStore()
PROFILE = ProfileService(DATA)
OPENAI = OpenAIClient()

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


class CopilotRequest(BaseModel):
    message: str
    session_id: str | None = None


@app.exception_handler(Exception)
async def handle_exception(_request: Request, exc: Exception):
    return _error(str(exc), status_code=400)


@app.get("/health", response_model=ApiEnvelope, tags=["System"])
def health():
    return _ok({"openai_configured": OPENAI.configured, "model": OPENAI.model})


@app.get("/households", response_model=ApiEnvelope, tags=["Frozen Data"])
def list_households():
    return _ok({"households": DATA.list_households()})


@app.get("/documents/match", response_model=ApiEnvelope, tags=["Profile"])
def match_document(file_name: str):
    doc = DATA.find_document(file_name=file_name)
    return _ok({"document": PROFILE.document_evidence(doc) if doc else None})


@app.get("/households/assess", response_model=ApiEnvelope, tags=["Understand"])
def assess_household(household_id: str):
    return _ok(PROFILE.assess(household_id))


@app.post("/sessions", response_model=ApiEnvelope, tags=["Session"])
def create_session():
    session = SESSIONS.create()
    return _ok({"session_id": session.session_id})


@app.post("/sessions/attach-document", response_model=ApiEnvelope, tags=["Profile"])
def attach_document(payload: AttachDocumentRequest):
    session = SESSIONS.get(payload.session_id)
    evidence = PROFILE.attach_document(
        session,
        file_name=payload.file_name,
        document_id=payload.document_id,
    )
    return _ok({"session_id": session.session_id, "document": evidence})


@app.post("/sessions/confirm-field", response_model=ApiEnvelope, tags=["Profile"])
def confirm_field(payload: ConfirmFieldRequest):
    session = SESSIONS.get(payload.session_id)
    confirmation = PROFILE.confirm_field(session, payload.document_id, payload.field, payload.value)
    packet = PROFILE.packet(session)
    return _ok({"confirmation": confirmation, "assessment": packet["assessment"]})


@app.post("/sessions/packet", response_model=ApiEnvelope, tags=["Prepare"])
def packet(payload: SessionRequest):
    return _ok(PROFILE.packet(SESSIONS.get(payload.session_id)))


@app.post("/sessions/delete", response_model=ApiEnvelope, tags=["Session"])
def delete_session(payload: SessionRequest):
    SESSIONS.delete(payload.session_id)
    return _ok({"deleted": True})


@app.post("/copilot", response_model=ApiEnvelope, tags=["Copilot"])
def copilot(payload: CopilotRequest):
    safety = assess_request_safety(payload.message)
    if not safety["allowed"]:
        return _ok({"safety": safety, "answer": safety["message"]})
    context = {}
    if payload.session_id:
        context = PROFILE.packet(SESSIONS.get(payload.session_id))
    return _ok({"safety": safety, "answer": OPENAI.explain(payload.message, context)})


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def _error(message: str, status_code: int = 400, code: str = "bad_request") -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "data": None, "error": {"code": code, "message": message}},
    )


def run(host: str = "127.0.0.1", port: int = 8000):
    uvicorn.run("src.api_server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run()
