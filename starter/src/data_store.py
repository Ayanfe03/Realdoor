import csv
import json
from functools import cached_property
from pathlib import Path

from .rules import load_rules


EVENT_DATE = "2026-07-18"


class DataStore:
    """Read-only access to the frozen challenge pack."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    @cached_property
    def documents(self) -> list[dict]:
        path = self.root / "synthetic_documents" / "gold" / "document_gold.jsonl"
        with path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    @cached_property
    def documents_by_id(self) -> dict[str, dict]:
        return {doc["document_id"]: doc for doc in self.documents}

    @cached_property
    def documents_by_filename(self) -> dict[str, dict]:
        return {doc["file_name"].lower(): doc for doc in self.documents}

    @cached_property
    def households(self) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {}
        for doc in self.documents:
            grouped.setdefault(doc["household_id"], []).append(doc)
        return grouped

    @cached_property
    def rules(self) -> dict[str, dict]:
        return load_rules(self.root / "rules" / "rule_corpus.jsonl")

    @cached_property
    def thresholds(self) -> dict[int, dict]:
        path = self.root / "data" / "mtsp_2026_boston_cambridge_quincy.csv"
        with path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return {int(row["household_size"]): row for row in rows}

    @cached_property
    def checklists(self) -> dict[str, dict]:
        path = self.root / "evaluation" / "application_checklists.json"
        with path.open(encoding="utf-8") as f:
            rows = json.load(f)
        return {row["household_id"]: row for row in rows}

    @cached_property
    def adversarial_tests(self) -> list[dict]:
        path = self.root / "evaluation" / "adversarial_tests.jsonl"
        with path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def find_document(self, *, file_name: str | None = None, document_id: str | None = None) -> dict | None:
        if document_id:
            return self.documents_by_id.get(document_id)
        if file_name:
            return self.documents_by_filename.get(Path(file_name).name.lower())
        return None

    def list_households(self) -> list[dict]:
        rows = []
        for household_id, docs in sorted(self.households.items()):
            checklist = self.checklists.get(household_id, {})
            rows.append(
                {
                    "household_id": household_id,
                    "household_size": checklist.get("household_size"),
                    "scenario": checklist.get("scenario"),
                    "document_count": len(docs),
                    "document_types": sorted({doc["document_type"] for doc in docs}),
                }
            )
        return rows

    def threshold_for(self, household_size: int) -> dict | None:
        row = self.thresholds.get(int(household_size))
        if not row:
            return None
        return {
            "household_size": int(row["household_size"]),
            "threshold": float(row["core_challenge_threshold"]),
            "effective_date": row["effective_date"],
            "hud_area": row["hud_area"],
            "fiscal_year": int(row["fiscal_year"]),
            "source_pdf_page": int(row["source_pdf_page"]),
            "source_url": row["source_url"],
        }

    def cite_rule(self, rule_id: str) -> dict:
        rule = self.rules[rule_id]
        return {
            "rule_id": rule["rule_id"],
            "effective_date": rule.get("effective_date"),
            "source_url": rule.get("source_url"),
            "source_locator": rule.get("source_locator"),
        }
