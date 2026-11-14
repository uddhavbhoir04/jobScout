from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ folder (this file is backend/src/jobscout/config.py)
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _resolve(p: str | Path) -> Path:
    """Relative paths in .env are relative to backend/, not to the current directory."""
    p = Path(p)
    return p if p.is_absolute() else BACKEND_ROOT / p


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/jobscout"
    fernet_key: str = ""

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    gemini_rpm: int = 8
    # Tried in order when the main model's free daily quota is used up (each has its own quota).
    gemini_fallback_models: str = "gemini-3.5-flash-lite,gemini-3.1-flash-lite"

    # LangChain: ordered "provider:model" list. Empty = GEMINI_MODEL + GEMINI_FALLBACK_MODELS.
    # e.g. google_genai:gemini-3.5-flash,openai:gpt-5-mini,groq:llama-3.3-70b-versatile,ollama:llama3.2
    llm_models: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    mistral_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    # Gemini is used for writing emails. Using it for post analysis too costs one call per
    # scanned post and burns the free quota fast, so scraping uses local rules by default.
    ai_extraction: bool = False

    gmail_user: str = ""
    gmail_app_password: str = ""
    sender_name: str = ""
    daily_email_cap: int = 50
    email_min_delay: int = 30
    email_max_delay: int = 90
    max_send_attempts: int = 3
    resume_path: str = ""
    profile_path: str = "PROFILE.md"
    # Mail server. Gmail by default; tests point this at a local fake SMTP server.
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_starttls: bool = True
    smtp_ssl_fallback_port: int = 465  # 0 disables the automatic port-465 retry

    default_phone_region: str = "US"
    headless: bool = False
    data_dir: Path = Path("data")

    # Web UI
    frontend_origin: str = "http://localhost:3000"
    # Each scrape / LinkedIn login runs a full Chrome on the server. Cap them across ALL users so a burst
    # of users can't exhaust the machine; extra requests get "busy, try again" (HTTP 503).
    max_browser_jobs: int = 2
    # Shared secret between the Next.js server and this API. When set, every /api request must carry it
    # in X-Internal-Key, so the API can't be called directly (only through the Next.js route handlers).
    internal_api_key: str | None = None
    # Production: serve over HTTPS and set COOKIE_SECURE=true so the session cookie is never sent over http.
    cookie_secure: bool = False
    # FastAPI's /docs and /openapi.json. Off automatically when internal_api_key is set.
    api_docs: bool = True

    def model_post_init(self, __context) -> None:
        self.data_dir = _resolve(self.data_dir)
        if self.resume_path:
            self.resume_path = str(_resolve(self.resume_path))
        self.profile_path = str(_resolve(self.profile_path))

    def profile_text(self) -> str:
        p = Path(self.profile_path)
        return p.read_text(encoding="utf-8") if p.is_file() else ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
