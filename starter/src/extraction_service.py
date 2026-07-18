import json
import re
from pathlib import Path
from uuid import uuid4

try:
    import fitz
except ImportError:  # pragma: no cover - guarded by runtime error
    fitz = None


ALLOWLISTED_FIELDS = {
    "person_name",
    "household_size",
    "address",
    "application_date",
    "pay_date",
    "pay_period_start",
    "pay_period_end",
    "pay_frequency",
    "regular_hours",
    "hourly_rate",
    "gross_pay",
    "net_pay",
    "document_date",
    "weekly_hours",
    "monthly_benefit",
    "benefit_frequency",
    "statement_month",
    "gross_receipts",
    "platform_fees",
}

NUMERIC_FIELDS = {
    "household_size",
    "regular_hours",
    "hourly_rate",
    "gross_pay",
    "net_pay",
    "weekly_hours",
    "monthly_benefit",
    "gross_receipts",
    "platform_fees",
}


class ExtractionService:
    def text_from_pdf(self, content: bytes) -> dict:
        if fitz is None:
            raise RuntimeError("PyMuPDF/fitz is required for PDF text extraction")
        doc = fitz.open(stream=content, filetype="pdf")
        pages = []
        for index, page in enumerate(doc, start=1):
            pages.append({"page": index, "text": page.get_text().strip()})
        return {
            "page_count": doc.page_count,
            "text": "\n\n".join(page["text"] for page in pages if page["text"]),
            "pages": pages,
        }

    def validate_model_result(self, model_result: dict, file_name: str | None = None) -> dict:
        raw_text = model_result.get("text") or ""
        parsed = _extract_json_object(raw_text)
        fields = parsed.get("fields", []) if isinstance(parsed, dict) else []
        abstentions = parsed.get("abstentions", []) if isinstance(parsed, dict) else ["Model did not return JSON"]
        validated_fields = []
        validation_errors = []
        for item in fields:
            if not isinstance(item, dict):
                validation_errors.append({"error": "field_item_not_object", "item": item})
                continue
            field_name = item.get("field")
            if field_name not in ALLOWLISTED_FIELDS:
                validation_errors.append({"error": "field_not_allowlisted", "field": field_name})
                continue
            value = _normalize_value(field_name, item.get("value"))
            validated_fields.append(
                {
                    "field": field_name,
                    "value": value,
                    "page": item.get("page", 1),
                    "bbox": item.get("bbox", [0, 0, 0, 0]),
                    "bbox_units": item.get("bbox_units", "text_extraction_no_bbox"),
                    "confidence": _confidence(item.get("confidence")),
                    "evidence_text": str(item.get("evidence_text", ""))[:240],
                    "confirmed": False,
                    "source": {
                        "document_id": None,
                        "page": item.get("page", 1),
                        "bbox": item.get("bbox", [0, 0, 0, 0]),
                        "bbox_units": item.get("bbox_units", "text_extraction_no_bbox"),
                    },
                }
            )
        status = "validated" if validated_fields else "abstained"
        return {
            "status": status,
            "document": {
                "document_id": f"AI-{uuid4()}",
                "household_id": None,
                "document_type": parsed.get("document_type", "unknown") if isinstance(parsed, dict) else "unknown",
                "file_name": file_name or "uploaded.pdf",
                "synthetic": True,
                "model_generated": True,
                "fields": validated_fields,
            },
            "validated_fields": validated_fields,
            "abstentions": abstentions,
            "validation_errors": validation_errors,
            "raw_model_text": raw_text,
        }


def _extract_json_object(text: str) -> dict:
    stripped = text.strip()
    if not stripped:
        return {"fields": [], "abstentions": ["Model returned an empty response"]}
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            return {"fields": [], "abstentions": ["Model response did not contain a JSON object"]}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {"fields": [], "abstentions": ["Model response JSON could not be parsed"]}


def _normalize_value(field_name: str, value):
    if field_name not in NUMERIC_FIELDS:
        return value
    if value is None or value == "":
        return value
    number = float(str(value).replace("$", "").replace(",", ""))
    if field_name == "household_size":
        return int(number)
    return number


def _confidence(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))
