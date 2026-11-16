"""Application configuration. All secrets come from environment variables."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """Minimal .env loader so users do not need an extra dependency."""
    for candidate in (BASE_DIR / ".env", BASE_DIR.parent / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


_load_dotenv()


class Settings:
    def __init__(self) -> None:
        self.openai_api_key: str | None = os.environ.get("OPENAI_API_KEY") or None
        # OpenRouter keys start with "sk-or-". They need OpenRouter's address and model names like "openai/gpt-6-luna".
        base = os.environ.get("OPENAI_BASE_URL") or None
        if not base and self.openai_api_key and self.openai_api_key.startswith("sk-or-"):
            base = "https://openrouter.ai/api/v1"
        self.openai_base_url: str | None = base
        self.using_openrouter: bool = bool(base and "openrouter.ai" in base)
        # "responses" = OpenAI Responses API. "chat" = Chat Completions with JSON-schema outputs (used for OpenRouter).
        self.openai_api_mode: str = os.environ.get("OPENAI_API_MODE") or ("chat" if self.using_openrouter else "responses")
        model = os.environ.get("OPENAI_MODEL", "gpt-6-luna")
        if self.using_openrouter and "/" not in model:
            model = "openai/" + model
        self.openai_model: str = model
        self.openai_timeout_seconds: float = float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "120"))
        self.openai_max_retries: int = int(os.environ.get("OPENAI_MAX_RETRIES", "2"))
        self.data_dir: Path = Path(os.environ.get("SENTINEL_DATA_DIR", str(BASE_DIR / "data")))
        self.database_url: str = os.environ.get(
            "SENTINEL_DATABASE_URL", f"sqlite:///{self.data_dir / 'sentinel.db'}"
        )
        self.max_upload_mb: int = int(os.environ.get("SENTINEL_MAX_UPLOAD_MB", "25"))
        self.max_files_per_investigation: int = int(os.environ.get("SENTINEL_MAX_FILES", "20"))
        self.cors_origins: list[str] = [
            o.strip()
            for o in os.environ.get(
                "SENTINEL_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
            ).split(",")
            if o.strip()
        ]
        # Maximum characters of document text sent to the Data Analyst agent.
        self.agent_context_char_budget: int = int(os.environ.get("SENTINEL_AGENT_CHAR_BUDGET", "60000"))
        self.max_questions: int = 5

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key)


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.uploads_dir.mkdir(parents=True, exist_ok=True)

SAMPLE_DIR = BASE_DIR / "sample_data" / "nova"
