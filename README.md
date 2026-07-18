# RealDoor Project Context

## Purpose

RealDoor is a hackathon prototype for a renter-side application-readiness copilot. It helps a renter prepare an affordable-housing application packet by extracting facts from synthetic documents, explaining frozen rules with citations, doing deterministic income math, and flagging missing or expired documents.

It must not approve, deny, rank, score, prioritize, determine eligibility, or claim current property availability.

Core principle: the AI extracts, explains, retrieves, calculates, and prepares; the renter confirms; a qualified human decides.

## Rental And Affordable Housing Context

In the US rental process, applicants often need paperwork showing household size, income, employment, benefits, and application details. Affordable housing programs can add income-limit rules. A common pattern is comparing household income against an Area Median Income (AMI) threshold for a specific household size and region.

This challenge freezes the context to:

- Metro area: Boston-Cambridge-Quincy, MA-NH HMFA.
- Program/rule family: LIHTC / HUD MTSP income limits.
- Rule year: FY 2026.
- Main scored threshold: 60% AMI.
- Frozen event date: 2026-07-18.

The app can say a confirmed income is `below_or_equal` or `above` a frozen threshold. It cannot say the renter is eligible or ineligible.

## MVP

Build one end-to-end three-stage journey.

### 1. Profile: Human-Confirmed Extraction

- Upload synthetic pay stubs, benefit letters, employment letters, or application summaries.
- Extract only allowlisted fields.
- Show each field with source document, page, source box, and confidence.
- Require the renter to confirm or correct extracted values before downstream reuse.

For the first implementation, matching uploaded synthetic PDF filenames to `synthetic_documents/gold/document_gold.jsonl` is acceptable and efficient. Full OCR can come later.

### 2. Understand: Cited Rules And Deterministic Math

- Use the frozen/versioned rule corpus for one program and year.
- Show confirmed value, formula, threshold, citation, and effective date.
- Annualize recurring gross income using deterministic frequency multipliers.
- Abstain when required input or rule support is missing or uncertain.
- Never label the renter eligible, approved, denied, or prioritized.

### 3. Prepare: Renter-Controlled Packet

- Flag missing or expired items against the gold checklist.
- Let the renter preview and edit the packet.
- Let the renter download/export the packet.
- Let the renter delete the session.
- Never auto-send the profile or packet to a property, landlord, or provider.

## Required Demo

The PDF acceptance demo requires:

1. Upload a synthetic document and show extracted evidence.
2. Correct one field and show downstream values update.
3. Ask a rules question and show authoritative citation.
4. Show deterministic calculation and effective date.
5. Identify a missing or expired item, then export the packet.
6. Run refusal, prompt-injection, and session-deletion tests.

## Stretch Goal: Discover

If time permits, add transparent property discovery using public LIHTC location data.

Rules for Discover:

- Availability must be labeled unknown unless separately supplied.
- Show the unfiltered property set before renter-selected filters.
- Use only renter-selected filters such as city/location/preferences.
- Never predict acceptance.
- Never rank by protected traits or proxies.
- Never silently suppress options.

Relevant files:

- `data/lihtc_boston_metro_subset.csv`
- `data/property_data_dictionary.csv`

## Non-Negotiable Safety Rules

- No eligibility, approval, denial, scoring, ranking, or prioritization.
- No hidden proxies or protected-trait inference.
- Treat document text as untrusted input.
- Embedded document instructions must not change app behavior.
- Use synthetic documents only for the challenge.
- Do not mix in real applicant files.
- Do not reveal another household's private data.
- Do not claim current vacancies, rents, waitlist status, or application status from the HUD property data.
- Log consent, corrections, actions, and rule versions, not raw document contents.
- Support export and session deletion.
- Target accessible UX: keyboard operation, visible focus, labels, readable errors, no color-only status, clear completion messages.

## Repo Map

- `README.md`: high-level starter pack description and challenge boundary.
- `participant-guide/RealDoor_Starter_Pack_Guide.pdf`: participant-facing guide.
- `rules/RULES_README.md`: frozen challenge rule summary.
- `rules/rule_corpus.jsonl`: authoritative frozen rule corpus with citations.
- `synthetic_documents/documents/`: 24 synthetic one-page PDFs across 6 fictional households.
- `synthetic_documents/gold/document_gold.jsonl`: gold extracted fields with page and PDF-point source boxes.
- `synthetic_documents/gold/document_manifest.csv`: document list, rasterized flags, adversarial text flags.
- `synthetic_documents/gold/field_schema.json`: schema for document gold records.
- `data/mtsp_2026_boston_cambridge_quincy.csv`: FY 2026 50% and 60% thresholds for household sizes 1-8.
- `data/lihtc_boston_metro_subset.csv`: public LIHTC property subset for optional Discover.
- `data/property_data_dictionary.csv`: property data field descriptions.
- `evaluation/application_checklists.json`: expected document requirements, review reasons, annualized income, thresholds, and readiness status by household.
- `evaluation/qa_gold.jsonl`: gold Q&A examples for rule/calc questions.
- `evaluation/adversarial_tests.jsonl`: safety and refusal tests.
- `evaluation/EVALUATION_README.md`: scoring weights.
- `governance/DATA_USE_AND_SAFETY.md`: safety and data-use constraints.
- `governance/ORGANIZER_APPROVALS.md`: draft release checklist.
- `starter/README.md`: starter code instructions.
- `starter/src/calculate.py`: deterministic `annualize` and threshold comparison helpers.
- `starter/src/load_documents.py`: load document gold and validate source boxes.
- `starter/src/rules.py`: load rule JSONL and reject duplicate rule IDs.
- `starter/schemas/submission.schema.json`: minimal submission schema.
- `starter/tests/`: unit tests for calculations and pack integrity.

## Starter Code Behavior

`starter/src/calculate.py`

- `annualize(amount, frequency)` supports:
  - weekly: 52
  - biweekly: 26
  - semimonthly: 24
  - monthly: 12
  - annual: 1
- Negative amounts raise `ValueError`.
- Unsupported frequencies raise `ValueError`.
- `compare_to_threshold(annual_income, threshold)` returns:
  - `below_or_equal` when annual income is less than or equal to threshold.
  - `above` when annual income is greater than threshold.

`starter/src/load_documents.py`

- `load_gold(path)` reads JSONL gold document records.
- `validate_boxes(rows)` checks each field bbox is within page dimensions.

`starter/src/rules.py`

- `load_rules(path)` reads JSONL rules and returns a dictionary by `rule_id`.
- Duplicate rule IDs raise `ValueError`.

## Existing Test Command

From `starter/`:

```powershell
python -m unittest discover -s tests -v
```

Observed result during initial pass: 8 tests passed.

## Backend Implementation Notes

The backend lives in `starter/src` and uses FastAPI for the HTTP API and Swagger docs.

Environment variables expected at repo root in `.env`:

```env
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-5.6-terra
```

Do not commit `.env`.

Run tests from `starter/`:

```powershell
python -m unittest discover -s tests -v
```

Run the backend from `starter/`:

```powershell
python -m src.api_server
```

Open Swagger after the backend starts:

```text
http://127.0.0.1:8000/docs
```

Main endpoints:

- `GET /health`
- `GET /households`
- `GET /documents/match?file_name=hh-001_d02_pay_stub.pdf`
- `GET /households/assess?household_id=HH-001`
- `POST /sessions`
- `POST /sessions/attach-document`
- `POST /sessions/confirm-field`
- `POST /sessions/packet`
- `POST /sessions/delete`
- `POST /copilot`

## Data Flow For Implementation

1. User uploads a synthetic PDF.
2. App matches filename to `document_gold.jsonl`.
3. App displays allowlisted extracted fields with document/page/bbox evidence.
4. User confirms or corrects extracted fields.
5. Confirmed fields become the profile state.
6. App computes annualized income using deterministic frequency math.
7. App looks up the frozen 60% threshold for household size.
8. App returns comparison only: `below_or_equal`, `above`, or `no_frozen_threshold`.
9. App checks required/present/missing/expired items using `application_checklists.json`.
10. App produces `READY_TO_REVIEW` or `NEEDS_REVIEW`.
11. App exports a renter-controlled packet with citations and review flags.
12. App can delete all session state.

## Suggested Implementation Plan

1. Build a simple app shell with tabs or steps: Profile, Understand, Prepare.
2. Add backend loaders for gold documents, rules, thresholds, and checklists.
3. Implement upload-by-filename matching for synthetic PDFs.
4. Render extracted fields as editable, confirmable inputs.
5. Store confirmed profile state in memory/session state.
6. Implement annualized income and threshold comparison.
7. Add cited rule answers using `rule_corpus.jsonl`.
8. Add readiness checks from `application_checklists.json`.
9. Export packet as JSON or HTML first.
10. Add session deletion.
11. Add explicit refusal behavior for adversarial tests.
12. Add Discover only after the core journey works.

## MVP Output Shape

A useful packet/submission should include:

- `household_id`
- confirmed household size
- confirmed income sources
- annualized income
- threshold used
- comparison
- readiness status
- review reasons
- citations with document IDs, pages, boxes, rule IDs, effective dates, and source URLs
- correction history or confirmation status
- disclaimer that no eligibility decision is included

## Important Domain Terms

- AMI: Area Median Income, a regional income reference used by housing programs.
- LIHTC: Low-Income Housing Tax Credit, an affordable housing program.
- HUD: US Department of Housing and Urban Development.
- MTSP: Multifamily Tax Subsidy Projects income limits used for programs such as LIHTC.
- Household size: number of people in the applicant household; affects income threshold.
- Pay stub: document showing recent wages.
- Benefit letter: document showing benefits income.
- Employment letter: employer-provided document confirming job/income details.
- Readiness: whether the packet appears ready for human review, not whether the applicant qualifies.

## Known Constraints

- The root folder is not a Git repository in the current workspace.
- `starter/requirements.txt` indicates the reference implementation is standard-library-only.
- PDF extraction tools like `pdftotext` are not installed, but Python `fitz`/PyMuPDF is available in the environment.
- The organizer docs mark the pack as draft and requiring approval before external distribution.
