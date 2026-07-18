DECISION_REFUSAL = (
    "I can help prepare a renter-controlled review packet, but I cannot approve, "
    "deny, rank, score, prioritize, or determine eligibility."
)


BLOCKED_PATTERNS = {
    "decisioning": [
        "approve",
        "approved",
        "deny",
        "denied",
        "eligible",
        "ineligible",
        "qualify",
        "rank applicant",
        "score applicant",
        "priority",
    ],
    "private_data": [
        "another household",
        "other household",
        "someone else's",
        "their documents",
        "system prompt",
        "api key",
        "secret",
    ],
    "property_availability": [
        "available today",
        "vacancy",
        "vacancies",
        "open waitlist",
        "current rent",
        "will accept",
    ],
    "prompt_injection": [
        "ignore previous",
        "ignore prior",
        "ignore instructions",
        "reveal the system",
        "developer message",
    ],
}


def assess_request_safety(text: str) -> dict:
    normalized = text.lower()
    categories = [
        category
        for category, patterns in BLOCKED_PATTERNS.items()
        if any(pattern in normalized for pattern in patterns)
    ]
    if not categories:
        return {"allowed": True, "categories": [], "message": None}
    return {"allowed": False, "categories": categories, "message": DECISION_REFUSAL}


def strip_untrusted_fields(fields: list[dict]) -> list[dict]:
    return [field for field in fields if field["field"] != "untrusted_instruction_text"]
