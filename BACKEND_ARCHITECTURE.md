# RealDoor Backend Architecture

This document explains the current RealDoor backend in simple terms. It is meant to help you understand what exists before frontend work begins.

## Big Picture

The backend is a FastAPI application for the RealDoor application-readiness copilot. It helps with three major jobs:

1. Profile: read synthetic renter documents, extract fields, and let the renter confirm or correct values.
2. Understand: explain frozen rules, compute deterministic income comparisons, and cite sources.
3. Prepare: produce a renter-controlled packet that a human can review.

The backend must not approve, deny, rank, score, prioritize, determine eligibility, or claim live property availability.

The main app file is:

- [starter/src/api_server.py](starter/src/api_server.py)

Run it from `starter/`:

```powershell
python -m src.api_server
```

Swagger docs:

```text
http://127.0.0.1:8000/docs
```

All application endpoints are under `/api`.

## Core Rule

The product principle from the challenge is:

```text
The AI extracts, explains, retrieves, calculates, and prepares.
The renter confirms.
A qualified human decides.
```

In this backend, that becomes:

- AI can help with extraction, explanation, and packet summaries.
- Deterministic code handles thresholds, math, readiness values, and safety boundaries.
- The renter confirms extracted fields before they are reused.
- The app never makes a final housing decision.

## Backend Responsibilities

The backend currently handles:

- Loading frozen challenge data.
- Creating in-memory sessions.
- Logging session actions with timestamps and rule versions.
- Matching synthetic PDFs to gold extraction records.
- Uploading PDFs and extracting text locally.
- Asking the model to extract allowlisted fields from text.
- Validating model extraction output before session use.
- Confirming or correcting fields.
- Annualizing income.
- Looking up frozen 2026 thresholds.
- Returning readiness status and review reasons.
- Answering rule questions with local rule/QA grounding.
- Calling OpenAI for grounded copilot responses and packet summaries.
- Exporting packets as JSON, HTML, or PDF.
- Deleting sessions.

## What AI Does

AI enters through [starter/src/openai_client.py](starter/src/openai_client.py).

The `OpenAIClient` methods are:

- `explain(prompt, context)`: low-level OpenAI Responses API call.
- `grounded_answer(prompt, context)`: used by the copilot after local grounding has been prepared.
- `extract_fields(text)`: asks the model to extract only allowlisted fields from document text.
- `packet_summary(packet)`: asks the model to summarize a packet without making a decision.

The model is configured by `.env` at repo root:

```env
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-5.6-terra
```

If no API key exists, the backend still works for deterministic/gold-fixture flows. Model endpoints return a clear "not configured" response instead of crashing.

## What Deterministic Code Does

The deterministic code is the source of truth for:

- Loading local files.
- Matching document IDs and filenames.
- Removing untrusted instruction fields.
- Annualizing income.
- Looking up thresholds.
- Comparing income to thresholds.
- Readiness status from the frozen checklist.
- Rule citations.
- Safety refusals.
- Export creation.

Important files:

- [starter/src/calculate.py](starter/src/calculate.py)
- [starter/src/data_store.py](starter/src/data_store.py)
- [starter/src/profile_service.py](starter/src/profile_service.py)
- [starter/src/rule_service.py](starter/src/rule_service.py)
- [starter/src/safety.py](starter/src/safety.py)
- [starter/src/export_service.py](starter/src/export_service.py)

## Data Sources

The backend reads these frozen project files:

- [synthetic_documents/gold/document_gold.jsonl](synthetic_documents/gold/document_gold.jsonl)
  - Gold extracted fields for synthetic documents.
  - Includes document IDs, household IDs, document types, field values, page numbers, and bounding boxes.

- [synthetic_documents/documents](synthetic_documents/documents)
  - Synthetic one-page PDF documents.

- [rules/rule_corpus.jsonl](rules/rule_corpus.jsonl)
  - Frozen rules and citations.

- [evaluation/qa_gold.jsonl](evaluation/qa_gold.jsonl)
  - Gold rule/calc Q&A examples.

- [evaluation/application_checklists.json](evaluation/application_checklists.json)
  - Expected annualized income, thresholds, readiness status, missing document types, and review reasons.

- [data/mtsp_2026_boston_cambridge_quincy.csv](data/mtsp_2026_boston_cambridge_quincy.csv)
  - Frozen 2026 threshold table.

- [evaluation/adversarial_tests.jsonl](evaluation/adversarial_tests.jsonl)
  - Safety/adversarial behavior references.

## Main Modules

### API Server

File:

- [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Defines the FastAPI app.
- Creates shared service instances.
- Defines request models.
- Defines all `/api` routes.
- Wraps normal JSON responses in a common envelope.

Common response envelope:

```json
{
  "ok": true,
  "data": {},
  "error": null
}
```

Error envelope:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "bad_request",
    "message": "..."
  }
}
```

### Data Store

File:

- [starter/src/data_store.py](starter/src/data_store.py)

Class:

- `DataStore`

Purpose:

- Loads frozen files from disk.
- Caches loaded data.
- Provides lookup helpers.

Important methods/properties:

- `documents`: loads `document_gold.jsonl`.
- `documents_by_id`: maps document ID to document.
- `documents_by_filename`: maps filename to document.
- `households`: groups documents by household.
- `rules`: loads `rule_corpus.jsonl`.
- `thresholds`: loads MTSP CSV.
- `checklists`: loads application checklist JSON.
- `qa_gold`: loads `qa_gold.jsonl`.
- `find_document(file_name, document_id)`: finds a gold synthetic document.
- `list_households()`: returns household summary cards.
- `threshold_for(household_size)`: returns frozen threshold row.
- `cite_rule(rule_id)`: returns citation metadata for a rule.

### Profile Service

File:

- [starter/src/profile_service.py](starter/src/profile_service.py)

Classes:

- `SessionState`
- `SessionStore`
- `ProfileService`

Purpose:

- Owns in-memory session state.
- Attaches documents to sessions.
- Stores confirmed/corrected fields.
- Adds validated AI-extracted documents to sessions.
- Produces packets.
- Computes deterministic assessment.
- Logs metadata-only actions.

Session state shape:

```python
SessionState(
    session_id="...",
    household_id=None,
    document_ids=[],
    extracted_documents={},
    confirmations={},
    actions=[],
    deleted=False,
)
```

Important methods:

- `SessionStore.create()`: creates a session and logs `session_created`.
- `SessionStore.get(session_id)`: retrieves active session.
- `SessionStore.delete(session_id)`: clears session state and marks deleted.
- `ProfileService.document_evidence(doc)`: converts a gold/model document into frontend-friendly evidence.
- `ProfileService.attach_document(session, file_name, document_id)`: attaches a gold synthetic document.
- `ProfileService.confirm_field(session, document_id, field_name, value)`: stores renter confirmation/correction.
- `ProfileService.add_extracted_document(session, extraction, household_id)`: attaches validated AI extraction.
- `ProfileService.packet(session)`: returns the packet preview.
- `ProfileService.record_consent(session, consent_type, granted)`: logs consent metadata.
- `ProfileService.record_export(session, export_type)`: logs export metadata.
- `ProfileService.assess(household_id, confirmations)`: returns annualized income, threshold, comparison, readiness, and citations.

Action log entries look like:

```json
{
  "action": "field_confirmed",
  "timestamp": "2026-07-19T...",
  "rule_version": "2026-07-18",
  "details": {
    "document_id": "HH-001-D02",
    "field": "gross_pay",
    "corrected": true
  }
}
```

The action log is local, in-memory, and metadata-only. It does not store raw document contents.

### Extraction Service

File:

- [starter/src/extraction_service.py](starter/src/extraction_service.py)

Class:

- `ExtractionService`

Purpose:

- Extracts text from uploaded PDFs.
- Validates model extraction responses.
- Allows only approved field names.
- Normalizes numeric values.
- Creates model-generated document records that can be confirmed.

Important constants:

- `ALLOWLISTED_FIELDS`
- `NUMERIC_FIELDS`

Important methods:

- `text_from_pdf(content)`: uses PyMuPDF/fitz to extract page text from PDF bytes.
- `validate_model_result(model_result, file_name)`: parses model text as JSON, filters to allowlisted fields, normalizes numeric fields, and returns validation errors/abstentions.

Validated extraction shape:

```json
{
  "status": "validated",
  "document": {
    "document_id": "AI-...",
    "household_id": null,
    "document_type": "pay_stub",
    "file_name": "uploaded.pdf",
    "synthetic": true,
    "model_generated": true,
    "fields": []
  },
  "validated_fields": [],
  "abstentions": [],
  "validation_errors": [],
  "raw_model_text": "{...}"
}
```

If no valid fields are returned:

```json
{
  "status": "abstained",
  "validated_fields": [],
  "abstentions": ["..."]
}
```

### Rule Service

File:

- [starter/src/rule_service.py](starter/src/rule_service.py)

Class:

- `RuleService`

Purpose:

- Retrieves relevant rules from the frozen rule corpus.
- Retrieves relevant examples from `qa_gold.jsonl`.
- Produces grounded rule answers.
- Adds abstentions for unsupported or out-of-scope questions.

Important methods:

- `retrieve(question, limit)`: keyword-based rule retrieval.
- `retrieve_qa(question, household_id, limit)`: keyword-based QA retrieval.
- `answer(question, household_id)`: safety-checks the question, retrieves rules/QA, adds citations, and returns an answer.

This is not a vector search system yet. That is acceptable because the corpus is small and already well-linked.

### OpenAI Client

File:

- [starter/src/openai_client.py](starter/src/openai_client.py)

Class:

- `OpenAIClient`

Purpose:

- Keeps OpenAI calls behind the backend boundary.
- Reads `.env` without exposing the key to the frontend.
- Calls the OpenAI Responses API.
- Provides guarded model methods.

Important methods:

- `configured`: true when an API key is available.
- `explain(prompt, context)`: generic model call.
- `grounded_answer(prompt, context)`: model call with rule/packet grounding.
- `extract_fields(text)`: model call for allowlisted document field extraction.
- `packet_summary(packet)`: model call for packet summary.

Important safety prompt idea:

```text
Never approve, deny, rank, score, prioritize, determine eligibility,
or claim current property availability.
```

### Safety

File:

- [starter/src/safety.py](starter/src/safety.py)

Purpose:

- Blocks obvious unsafe requests before model calls.
- Removes untrusted instruction fields from extracted evidence.

Important functions:

- `assess_request_safety(text)`: checks for decisioning, private data, property availability, and prompt-injection patterns.
- `strip_untrusted_fields(fields)`: removes `untrusted_instruction_text` from document fields.

### Export Service

File:

- [starter/src/export_service.py](starter/src/export_service.py)

Class:

- `ExportService`

Purpose:

- Creates packet exports.

Important methods:

- `packet_json(packet)`: JSON export wrapper.
- `packet_html(packet)`: simple HTML packet.
- `packet_pdf(packet)`: simple PDF packet using PyMuPDF/fitz.

## Endpoint Details

### GET `/api/health`

Defined in:

- `health()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Confirms the backend is running.
- Confirms whether OpenAI is configured.
- Shows the selected model.

Input:

None.

Response comes from:

- `OPENAI.configured`
- `OPENAI.model`

Example output:

```json
{
  "ok": true,
  "data": {
    "openai_configured": true,
    "model": "gpt-5.6-terra"
  },
  "error": null
}
```

AI involvement:

- No model call.
- Only checks whether config exists.

Frontend use:

- Show backend/API status.
- Optionally show whether AI features are available.

### GET `/api/households`

Defined in:

- `list_households()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Lists the synthetic households available in the frozen pack.

Input:

None.

Response comes from:

- `DataStore.list_households()` in [starter/src/data_store.py](starter/src/data_store.py)
- `DataStore.households`
- `DataStore.checklists`

Example output:

```json
{
  "ok": true,
  "data": {
    "households": [
      {
        "household_id": "HH-001",
        "household_size": 1,
        "scenario": "regular_hourly",
        "document_count": 4,
        "document_types": ["application_summary", "employment_letter", "pay_stub"]
      }
    ]
  },
  "error": null
}
```

AI involvement:

- None.

Frontend use:

- Helpful for demo selectors.
- Lets the UI choose a household before upload.

### GET `/api/documents/match`

Defined in:

- `match_document()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Finds a synthetic document by filename and returns known extracted evidence.

Input query:

```text
file_name=hh-001_d02_pay_stub.pdf
```

Response comes from:

- `DataStore.find_document(file_name=...)`
- `ProfileService.document_evidence(doc)`

Example output:

```json
{
  "ok": true,
  "data": {
    "document": {
      "document_id": "HH-001-D02",
      "household_id": "HH-001",
      "document_type": "pay_stub",
      "file_name": "hh-001_d02_pay_stub.pdf",
      "fields": []
    }
  },
  "error": null
}
```

AI involvement:

- None.
- This is the gold-fixture path.

Frontend use:

- Filename lookup.
- Can power synthetic demo extraction without spending model tokens.

### GET `/api/households/assess`

Defined in:

- `assess_household()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Computes the deterministic assessment for a household.

Input query:

```text
household_id=HH-001
```

Response comes from:

- `ProfileService.assess(household_id)`
- `ProfileService._annualized_income(...)`
- `annualize(...)` and `compare_to_threshold(...)` in [starter/src/calculate.py](starter/src/calculate.py)
- `DataStore.threshold_for(...)`
- `DataStore.cite_rule(...)`
- `application_checklists.json`

Example output:

```json
{
  "household_id": "HH-001",
  "household_size": 1,
  "annualized_income": 56316.0,
  "threshold": {
    "threshold": 72000.0,
    "effective_date": "2026-05-01"
  },
  "comparison": "below_or_equal",
  "readiness_status": "READY_TO_REVIEW",
  "review_reasons": [],
  "citations": []
}
```

AI involvement:

- None.
- This endpoint is intentionally deterministic.

Frontend use:

- Display calculation result.
- Display threshold comparison.
- Display citations/effective date.

### POST `/api/sessions`

Defined in:

- `create_session()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Creates a new in-memory session for the renter's current workflow.

Input:

No body required.

Response comes from:

- `SessionStore.create()` in [starter/src/profile_service.py](starter/src/profile_service.py)

Example output:

```json
{
  "ok": true,
  "data": {
    "session_id": "..."
  },
  "error": null
}
```

Side effect:

- Logs `session_created`.

AI involvement:

- None.

Frontend use:

- First call when the app loads or when the renter starts a new packet.

### POST `/api/sessions/consent`

Defined in:

- `record_consent()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Records that the renter gave or denied consent for a specific data-use action.

Input body:

```json
{
  "session_id": "PASTE_SESSION_ID",
  "consent_type": "process_synthetic_document",
  "granted": true
}
```

Request model:

- `ConsentRequest` in [starter/src/api_server.py](starter/src/api_server.py)

Response comes from:

- `SessionStore.get(session_id)`
- `ProfileService.record_consent(session, consent_type, granted)`

Example output:

```json
{
  "ok": true,
  "data": {
    "event": {
      "action": "consent_recorded",
      "timestamp": "...",
      "rule_version": "2026-07-18",
      "details": {
        "consent_type": "process_synthetic_document",
        "granted": true
      }
    }
  },
  "error": null
}
```

AI involvement:

- None.

Frontend use:

- Call this after explaining data use and before upload/extraction.

### POST `/api/extraction/upload`

Defined in:

- `upload_pdf_for_extraction()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Uploads a PDF and extracts fields.
- Has two paths:
  - Known synthetic filename: use gold fixture, no model call.
  - Unknown PDF: extract text locally, optionally call OpenAI, validate output.

Input form fields:

```text
file: PDF file
session_id: optional session ID
household_id: optional household ID
use_model: true or false
```

Response path 1: known synthetic file

If the filename matches `document_gold.jsonl`, for example `hh-001_d02_pay_stub.pdf`:

- `DataStore.find_document(file_name=file.filename)`
- `ProfileService.document_evidence(known_doc)`
- optionally `ProfileService.attach_document(session, file_name=file.filename)`

Example output:

```json
{
  "mode": "gold_fixture",
  "file_name": "hh-001_d02_pay_stub.pdf",
  "document": {},
  "attached_document": {},
  "note": "Filename matched the frozen synthetic gold set; no model call was made."
}
```

Response path 2: unknown PDF

If the filename is not in the gold set:

- `ExtractionService.text_from_pdf(content)` extracts text locally.
- `OpenAIClient.extract_fields(text)` is called if `use_model` is true.
- `ExtractionService.validate_model_result(model_result)` validates allowlisted fields.
- `ProfileService.add_extracted_document(...)` attaches validated model fields to the session if possible.

Example output:

```json
{
  "mode": "pdf_text_model_validation",
  "file_name": "uploaded.pdf",
  "text": {
    "page_count": 1,
    "text": "...",
    "pages": []
  },
  "model_result": {},
  "validated": {
    "status": "validated",
    "validated_fields": [],
    "abstentions": [],
    "validation_errors": []
  },
  "attached_document": {},
  "note": "Raw PDF text is returned for local review; do not persist raw document text outside the session boundary."
}
```

AI involvement:

- None for known synthetic filenames.
- Yes for unknown PDFs when `use_model=true` and OpenAI is configured.

Frontend use:

- Main upload flow.
- For demo, use known synthetic PDFs first.

### POST `/api/extraction/preview`

Defined in:

- `extraction_preview()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Preview extraction without a file upload.
- Can use gold fixture by document ID/filename.
- Can use text/model extraction preview.

Input body for gold fixture:

```json
{
  "document_id": "HH-001-D02"
}
```

Input body for text/model preview:

```json
{
  "text": "Employee: Mara North\nGross pay: 2166\nPay frequency: biweekly"
}
```

Response comes from:

- `DataStore.find_document(...)`
- `ProfileService.extraction_preview(...)`
- `OpenAIClient.extract_fields(...)`
- `ExtractionService.validate_model_result(...)`

AI involvement:

- None for gold fixture.
- Yes for raw text input, if OpenAI is configured.

Frontend use:

- Useful for a manual extraction/debug panel.
- Less important than `/api/extraction/upload` for the final UI.

### POST `/api/sessions/attach-document`

Defined in:

- `attach_document()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Attaches a known gold synthetic document to a session.

Input body:

```json
{
  "session_id": "PASTE_SESSION_ID",
  "document_id": "HH-001-D02"
}
```

Alternative:

```json
{
  "session_id": "PASTE_SESSION_ID",
  "file_name": "hh-001_d02_pay_stub.pdf"
}
```

Response comes from:

- `SessionStore.get(session_id)`
- `ProfileService.attach_document(...)`
- `DataStore.find_document(...)`
- `ProfileService.document_evidence(...)`

Side effect:

- Logs `document_attached`.

AI involvement:

- None.

Frontend use:

- Can be used when selecting a synthetic fixture instead of uploading.

### POST `/api/sessions/confirm-field`

Defined in:

- `confirm_field()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Lets the renter confirm or correct an extracted field.
- Recalculates downstream assessment immediately.

Input body:

```json
{
  "session_id": "PASTE_SESSION_ID",
  "document_id": "HH-001-D02",
  "field": "gross_pay",
  "value": 1000
}
```

Response comes from:

- `SessionStore.get(session_id)`
- `ProfileService.confirm_field(...)`
- `ProfileService.packet(...)`
- `ProfileService.assess(...)`

Example output:

```json
{
  "ok": true,
  "data": {
    "confirmation": {
      "document_id": "HH-001-D02",
      "field": "gross_pay",
      "original_value": 2166.0,
      "value": 1000,
      "corrected": true,
      "source": {}
    },
    "assessment": {
      "annualized_income": 26000,
      "comparison": "below_or_equal"
    }
  },
  "error": null
}
```

Side effect:

- Logs `field_confirmed`.

AI involvement:

- None.
- This is the renter-confirmation part of the product.

Frontend use:

- Editable extracted fields.
- Update calculations live after correction.

### POST `/api/rules/answer`

Defined in:

- `answer_rule_question()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Answers a rule question using frozen local rules and QA examples.

Input body:

```json
{
  "question": "What is the frozen 60% threshold for HH-001?",
  "household_id": "HH-001"
}
```

Response comes from:

- `RuleService.answer(question, household_id)`
- `RuleService.retrieve(...)`
- `RuleService.retrieve_qa(...)`
- `DataStore.rules`
- `DataStore.qa_gold`
- `DataStore.threshold_for(...)`

Example output:

```json
{
  "status": "grounded",
  "answer": "For HH-001, the confirmed household size is 1...",
  "rules": [],
  "qa_matches": [],
  "abstentions": [],
  "citations": []
}
```

AI involvement:

- None.
- This is deterministic retrieval/explanation.

Frontend use:

- Rules Q&A panel.
- Show citations and abstentions.

### POST `/api/copilot`

Defined in:

- `copilot()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Main AI copilot endpoint.
- Safety-checks the message first.
- Retrieves local rule grounding.
- Adds session packet context if a session ID is provided.
- Calls OpenAI for a grounded response.

Input body:

```json
{
  "message": "Explain the 60% threshold for this household.",
  "session_id": "PASTE_SESSION_ID"
}
```

Response comes from:

- `assess_request_safety(message)`
- `RuleService.answer(message, household_id)`
- `ProfileService.packet(session)` if session ID exists.
- `OpenAIClient.grounded_answer(message, context)`

Refusal input:

```json
{
  "message": "Can you approve this renter?"
}
```

Refusal output:

```json
{
  "safety": {
    "allowed": false,
    "categories": ["decisioning"],
    "message": "I can help prepare..."
  },
  "answer": "I can help prepare..."
}
```

AI involvement:

- Refused requests do not call the model.
- Safe requests call the model if OpenAI is configured.

Frontend use:

- Chat/copilot panel.
- Explain extracted facts and rules.
- Must display refusals cleanly.

### POST `/api/sessions/packet`

Defined in:

- `packet()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Returns the current packet preview.

Input body:

```json
{
  "session_id": "PASTE_SESSION_ID"
}
```

Response comes from:

- `SessionStore.get(session_id)`
- `ProfileService.packet(session)`
- `ProfileService.assess(...)`

Packet includes:

- `session_id`
- `household_id`
- `documents`
- `confirmations`
- `action_log`
- `assessment`
- `decision_boundary`

AI involvement:

- None.

Frontend use:

- Prepare step packet preview.
- Show confirmed values, review reasons, citations, and action log if needed.

### POST `/api/sessions/summary`

Defined in:

- `packet_summary()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Produces an AI-written packet summary.

Input body:

```json
{
  "session_id": "PASTE_SESSION_ID"
}
```

Response comes from:

- `ProfileService.packet(session)`
- `OpenAIClient.packet_summary(packet)`

Example output:

```json
{
  "summary": {
    "status": "summarized",
    "summary": "...",
    "review_reasons": [],
    "abstentions": []
  },
  "packet": {}
}
```

AI involvement:

- Yes, if OpenAI is configured.
- If not configured, returns deterministic fallback text.

Frontend use:

- Friendly packet summary.
- Optional for MVP, but useful for copilot feel.

### POST `/api/sessions/export`

Defined in:

- `export_packet()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Returns a JSON export object inside the normal API envelope.

Input body:

```json
{
  "session_id": "PASTE_SESSION_ID"
}
```

Response comes from:

- `ProfileService.record_export(session, "json")`
- `ProfileService.packet(session)`
- `ExportService.packet_json(packet)`

Side effect:

- Logs `packet_exported`.

AI involvement:

- None.

Frontend use:

- JSON packet export.
- Useful for debugging and demo output.

### POST `/api/sessions/export-file`

Defined in:

- `export_packet_file()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Returns a downloadable file response.

Input body:

```json
{
  "session_id": "PASTE_SESSION_ID",
  "format": "html"
}
```

Allowed formats:

- `json`
- `html`
- `pdf`

Response comes from:

- `ProfileService.packet(session)`
- `ProfileService.record_export(session, format)`
- `ExportService.packet_json(packet)`
- `ExportService.packet_html(packet)`
- `ExportService.packet_pdf(packet)`

Response type:

- JSON: `application/json`
- HTML: `text/html`
- PDF: `application/pdf`

AI involvement:

- None.

Frontend use:

- Download button.
- The frontend can call it and save the returned file.

### POST `/api/sessions/delete`

Defined in:

- `delete_session()` in [starter/src/api_server.py](starter/src/api_server.py)

Purpose:

- Deletes the in-memory session.

Input body:

```json
{
  "session_id": "PASTE_SESSION_ID"
}
```

Response comes from:

- `SessionStore.delete(session_id)`

What gets cleared:

- `document_ids`
- `extracted_documents`
- `confirmations`
- `household_id`

What happens:

- Logs `session_deleted`.
- Marks session as deleted.
- Future access to that session raises an error.

AI involvement:

- None.

Frontend use:

- Delete session button.
- Should reset local UI state afterward.

## Recommended Frontend Flow

### Step 1: Start

Call:

```text
POST /api/sessions
```

Store `session_id` in frontend state.

### Step 2: Consent

Show a short explanation:

```text
We will process this synthetic document to extract fields for your review.
```

Call:

```text
POST /api/sessions/consent
```

### Step 3: Upload

Call:

```text
POST /api/extraction/upload
```

For the demo, choose a synthetic PDF from:

```text
synthetic_documents/documents/
```

If the filename is known, the backend uses gold extraction and avoids a model call.

### Step 4: Confirm Fields

For each displayed field, call:

```text
POST /api/sessions/confirm-field
```

The response includes an updated assessment.

### Step 5: Explain Rules

Call:

```text
POST /api/rules/answer
```

or:

```text
POST /api/copilot
```

Use `/api/rules/answer` for deterministic cited answers.
Use `/api/copilot` for natural AI interaction.

### Step 6: Preview Packet

Call:

```text
POST /api/sessions/packet
```

### Step 7: Export

Call:

```text
POST /api/sessions/export-file
```

Use `format: "html"` or `format: "pdf"` for a user-facing download.

### Step 8: Delete

Call:

```text
POST /api/sessions/delete
```

Then clear frontend state.

## Privacy And Observability

Current backend posture:

- Sessions are in-memory.
- Action logs are in-memory.
- Action logs store metadata only.
- Raw document text is not persisted.
- Uploaded PDFs are not stored on disk by this backend.
- External tracing/storage such as Supabase or Arize is not currently used.

Why not external tracing yet:

- The challenge emphasizes renter privacy and minimal retention.
- External traces can accidentally capture prompts, names, addresses, extracted values, or raw document text.
- The MVP does not need external observability to demonstrate the required journey.

If observability is added later:

- Do not log raw document text.
- Do not log uploaded files.
- Do not log API keys or prompts containing private fields.
- Redact names, addresses, income values, and document contents.
- Prefer aggregate counters and metadata-only audit events.

## Current Limitations

Important limitations to remember:

- Sessions are in-memory, so data disappears when the server restarts.
- AI extraction from unknown PDFs depends on the model returning parseable JSON.
- Validation filters model output, but the model call is not yet using a strict API-level JSON schema.
- The PDF export is intentionally simple.
- The HTML export is intentionally simple.
- No frontend exists yet.
- No real OCR for scanned image-only PDFs beyond whatever text PyMuPDF can extract.
- No external database.
- No production authentication.
- No persistent audit log.

## Test Coverage

Main tests:

- [starter/tests/test_api_server.py](starter/tests/test_api_server.py)
- [starter/tests/test_backend_services.py](starter/tests/test_backend_services.py)
- [starter/tests/test_calculate.py](starter/tests/test_calculate.py)
- [starter/tests/test_pack_integrity.py](starter/tests/test_pack_integrity.py)

Run tests:

```powershell
cd starter
python -m unittest discover -s tests -v
```

Current expected result:

```text
Ran 26 tests
OK
```

The tests cover:

- API health.
- Legacy route removal.
- Household assessment.
- Session creation and field confirmation.
- Safety refusal.
- Rules answer with QA matches.
- Gold extraction preview.
- Consent event.
- Uploading known synthetic PDF without a model call.
- JSON export.
- HTML export.
- PDF export.
- Packet summary boundary.
- Pack integrity.
- Calculation helpers.

## Backend Readiness Before Frontend

The backend is ready enough to begin frontend work.

Frontend should focus on:

- A clear Profile -> Understand -> Prepare journey.
- Upload/consent flow.
- Editable extracted fields.
- Evidence display using source boxes.
- Calculation and threshold display.
- Rules/citations display.
- Packet preview and download.
- Delete session.
- Refusal and safety behavior.

The biggest frontend-dependent requirement is source-box visualization. The backend already returns page and bbox metadata; the frontend needs to render documents and overlays.
