import json
import os
from pathlib import Path
import urllib.error
import urllib.request

try:
    from dotenv import dotenv_values
except ImportError:  # pragma: no cover - fallback for minimal environments
    dotenv_values = None


DEFAULT_MODEL = "gpt-5.6-terra"


class OpenAIClient:
    """Small Responses API wrapper kept behind the backend boundary."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        env_file = _load_root_env()
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            self.api_key = env_file.get("OPENAI_API_KEY")
        self.model = model or os.environ.get("OPENAI_MODEL") or env_file.get("OPENAI_MODEL", DEFAULT_MODEL)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def explain(self, prompt: str, context: dict) -> dict:
        if not self.configured:
            return {
                "configured": False,
                "model": self.model,
                "text": "OpenAI is not configured. Add OPENAI_API_KEY in the root .env before enabling model calls.",
            }
        body = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are RealDoor, an application-readiness copilot. Explain, extract, retrieve, "
                        "calculate through provided values, and prepare. Never approve, deny, rank, score, "
                        "prioritize, determine eligibility, or claim current property availability."
                    ),
                },
                {"role": "user", "content": f"Context JSON:\n{json.dumps(context, indent=2)}\n\nQuestion:\n{prompt}"},
            ],
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            return {"configured": True, "model": self.model, "error": str(exc)}
        return {"configured": True, "model": self.model, "text": _response_text(payload), "raw": payload}


def _response_text(payload: dict) -> str:
    parts = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and "text" in content:
                parts.append(content["text"])
    return "\n".join(parts).strip()


def _load_root_env() -> dict[str, str]:
    env_path = _find_root_env()
    if not env_path:
        return {}
    if dotenv_values:
        return {key: value for key, value in dotenv_values(env_path).items() if value is not None}
    values = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _find_root_env() -> Path | None:
    candidates = [Path.cwd(), Path(__file__).resolve()]
    for start in candidates:
        current = start if start.is_dir() else start.parent
        for parent in [current, *current.parents]:
            env_path = parent / ".env"
            if env_path.exists():
                return env_path
    return None
