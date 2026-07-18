from .data_store import DataStore
from .safety import assess_request_safety


RULE_KEYWORDS = {
    "HUD-MTSP-001": ["effective", "date", "mtsp", "2026"],
    "HUD-MTSP-002": ["60", "ami", "threshold", "limit", "household", "income"],
    "HUD-MTSP-003": ["50", "ami", "threshold", "limit"],
    "HUD-DATA-001": ["property", "availability", "vacancy", "waitlist", "rent"],
    "CH-INCOME-001": ["annualize", "annualized", "income", "frequency", "gross"],
    "CH-READINESS-001": ["ready", "readiness", "missing", "expired", "current", "60 days"],
    "CH-SAFETY-001": ["prompt", "injection", "untrusted", "document", "secret"],
    "CH-DECISION-001": ["eligible", "eligibility", "approve", "deny", "decision"],
}


class RuleService:
    def __init__(self, store: DataStore):
        self.store = store

    def retrieve_qa(self, question: str, household_id: str | None = None, limit: int = 3) -> list[dict]:
        normalized = question.lower()
        scored = []
        for qa in self.store.qa_gold:
            if household_id and qa.get("household_id") not in {household_id, None}:
                continue
            score = sum(1 for word in normalized.split() if len(word) > 3 and word in qa["question"].lower())
            if household_id and qa.get("household_id") == household_id:
                score += 2
            if score:
                scored.append((score, qa))
        scored.sort(key=lambda item: -item[0])
        return [qa for _score, qa in scored[:limit]]

    def retrieve(self, question: str, limit: int = 4) -> list[dict]:
        normalized = question.lower()
        scored = []
        for rule_id, rule in self.store.rules.items():
            keywords = RULE_KEYWORDS.get(rule_id, [])
            score = sum(1 for keyword in keywords if keyword in normalized)
            if score == 0:
                score = sum(1 for word in normalized.split() if len(word) > 3 and word in rule["text"].lower())
            if score:
                scored.append((score, rule_id, rule))
        if not scored:
            fallback_ids = ["HUD-MTSP-002", "CH-INCOME-001", "CH-READINESS-001", "CH-DECISION-001"]
            return [self._public_rule(self.store.rules[rule_id]) for rule_id in fallback_ids]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [self._public_rule(rule) for _score, _rule_id, rule in scored[:limit]]

    def answer(self, question: str, household_id: str | None = None) -> dict:
        safety = assess_request_safety(question)
        if not safety["allowed"]:
            return {
                "status": "refused",
                "answer": safety["message"],
                "safety": safety,
                "citations": [self.store.cite_rule("CH-SAFETY-001"), self.store.cite_rule("CH-DECISION-001")],
            }
        rules = self.retrieve(question)
        qa_matches = self.retrieve_qa(question, household_id=household_id)
        household_context = None
        if household_id:
            checklist = self.store.checklists.get(household_id)
            if checklist:
                threshold = self.store.threshold_for(checklist["household_size"])
                household_context = {
                    "household_id": household_id,
                    "household_size": checklist["household_size"],
                    "threshold": threshold,
                }
        return {
            "status": "grounded",
            "answer": _compose_answer(question, rules, household_context),
            "rules": rules,
            "qa_matches": qa_matches,
            "abstentions": _abstentions(question, rules, qa_matches),
            "citations": [
                {
                    "rule_id": rule["rule_id"],
                    "effective_date": rule.get("effective_date"),
                    "source_url": rule.get("source_url"),
                    "source_locator": rule.get("source_locator"),
                }
                for rule in rules
            ],
        }

    def _public_rule(self, rule: dict) -> dict:
        return {
            "rule_id": rule["rule_id"],
            "authority": rule.get("authority"),
            "effective_date": rule.get("effective_date"),
            "text": rule["text"],
            "source_url": rule.get("source_url"),
            "source_locator": rule.get("source_locator"),
        }


def _compose_answer(question: str, rules: list[dict], household_context: dict | None) -> str:
    if household_context and household_context.get("threshold"):
        threshold = household_context["threshold"]
        return (
            f"For {household_context['household_id']}, the confirmed household size is "
            f"{household_context['household_size']}. The frozen FY {threshold['fiscal_year']} 60% "
            f"threshold for this challenge is ${threshold['threshold']:,.0f}, effective "
            f"{threshold['effective_date']}. I can compare confirmed income with that threshold, "
            "but I cannot decide eligibility."
        )
    first = rules[0]
    return (
        f"Using the frozen RealDoor rule corpus, the most relevant rule is {first['rule_id']}: "
        f"{first['text']} This is readiness guidance only; a qualified human decides."
    )


def _abstentions(question: str, rules: list[dict], qa_matches: list[dict]) -> list[str]:
    normalized = question.lower()
    abstentions = []
    if not rules and not qa_matches:
        abstentions.append("No supporting frozen rule or gold Q&A record was found.")
    if any(term in normalized for term in ["today", "available", "vacancy", "open unit", "waitlist"]):
        abstentions.append("Current availability, waitlist, live rent, and application status are outside the frozen corpus.")
    if any(term in normalized for term in ["should i apply", "will i get", "approve", "deny", "eligible"]):
        abstentions.append("The system cannot make eligibility, approval, denial, ranking, or priority decisions.")
    return abstentions
