"""Provider-agnostic chat model access via LangChain, with free-tier quota handling.

Models are configured as an ordered list of "provider:model" in LLM_MODELS, e.g.
    LLM_MODELS=google_genai:gemini-3.5-flash,google_genai:gemini-3.5-flash-lite,groq:llama-3.3-70b-versatile
They are tried in order: a per-minute rate limit waits and retries; a daily/plan quota or a missing
model moves on to the next one. Supported providers are whatever LangChain's init_chat_model supports
and is installed (google_genai is installed by default; see pyproject extras for openai/anthropic/groq/ollama).
"""
import json
import logging
import re
import time
from dataclasses import dataclass
from functools import lru_cache

from jobscout.config import Settings, get_settings

log = logging.getLogger(__name__)

TIMEOUT_S = 30
MAX_QUOTA_WAIT_S = 65.0

# provider -> Settings attribute holding its API key ("" = no key needed, e.g. local Ollama)
PROVIDER_KEYS = {
    "google_genai": "gemini_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "groq": "groq_api_key",
    "mistralai": "mistral_api_key",
    "ollama": "",
}
PROVIDER_PACKAGES = {
    "google_genai": "langchain-google-genai",
    "openai": "langchain-openai",
    "anthropic": "langchain-anthropic",
    "groq": "langchain-groq",
    "mistralai": "langchain-mistralai",
    "ollama": "langchain-ollama",
}

# "provider:model" -> monotonic time until which it is unusable (quota used up / missing). Shared by all jobs.
_EXHAUSTED_UNTIL: dict[str, float] = {}


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


def parse_models(settings: Settings) -> list[ModelSpec]:
    raw = settings.llm_models.strip()
    if not raw:  # backwards compatible: GEMINI_MODEL + GEMINI_FALLBACK_MODELS
        names = [settings.gemini_model] + [m.strip() for m in settings.gemini_fallback_models.split(",")]
        raw = ",".join(f"google_genai:{n}" for n in names if n)
    out: list[ModelSpec] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        provider, _, model = item.partition(":")
        if not model:  # bare model name -> Gemini
            provider, model = "google_genai", provider
        spec = ModelSpec(provider.strip(), model.strip())
        if spec not in out:
            out.append(spec)
    return out


def _seconds_until_quota_reset() -> float:
    """Gemini's daily free quota resets at midnight Pacific time; good enough as a default for others."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
    return (midnight - now).total_seconds()


def classify_quota_error(err: Exception) -> tuple[str, float | None] | None:
    """Rate-limit / quota error from any provider -> ("day"|"minute", retry delay seconds). Else None."""
    text = f"{type(err).__name__} {err}"
    if not re.search(r"429|RESOURCE_EXHAUSTED|RateLimit|rate[_ ]limit|insufficient_quota|quota", text, re.I):
        return None
    m = (re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s", text)
         or re.search(r"try again in\s+(\d+(?:\.\d+)?)\s*s", text, re.I)
         or re.search(r"retry[- ]after['\"]?\s*[:=]?\s*(\d+(?:\.\d+)?)", text, re.I))
    delay = float(m.group(1)) if m else None
    if re.search(r"PerDay|per day|daily|insufficient_quota|exceeded your current quota.*billing", text, re.I | re.S):
        if re.search(r"PerMinute|per minute", text, re.I) and not re.search(r"PerDay|per day", text, re.I):
            return "minute", delay
        return "day", delay
    return "minute", delay


def is_permanent(err: Exception) -> bool:
    text = f"{type(err).__name__} {err}"
    return bool(re.search(r"API_KEY_INVALID|PERMISSION_DENIED|UNAUTHENTICATED|invalid[_ ]api[_ ]key|"
                          r"AuthenticationError|\b401\b|\b403\b", text, re.I))


def model_missing(err: Exception) -> bool:
    text = f"{type(err).__name__} {err}"
    return bool(re.search(r"NOT_FOUND|\b404\b|model_not_found|does not exist|ModuleNotFoundError|"
                          r"Unable to import|pip install", text, re.I))


def parse_json(text: str) -> dict:
    """Tolerant JSON extraction: strips ``` fences and surrounding prose."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


@lru_cache(maxsize=16)
def _chat_model(provider: str, model: str, api_key: str, temperature: float):
    from langchain.chat_models import init_chat_model

    kwargs = {"temperature": temperature, "timeout": TIMEOUT_S, "max_retries": 0}
    if api_key:
        kwargs["api_key"] = api_key
    if provider == "ollama":
        kwargs.pop("timeout")
        kwargs["base_url"] = get_settings().ollama_base_url
    return init_chat_model(model, model_provider=provider, **kwargs)


class LLM:
    """Ordered list of chat models with rate-limit waits and quota fallbacks."""

    def __init__(self, settings: Settings | None = None, temperature: float = 0.4):
        self.settings = settings or get_settings()
        self.temperature = temperature
        self._last_call = 0.0
        self._rpm = max(1, self.settings.gemini_rpm)
        self._disabled_reason: str | None = None
        self.models: list[ModelSpec] = []
        for spec in parse_models(self.settings):
            attr = PROVIDER_KEYS.get(spec.provider)
            if attr is None or (attr and not getattr(self.settings, attr, "")):
                log.debug("Skipping %s: no API key configured", spec.key)
                continue
            self.models.append(spec)
        if not self.models:
            self._disabled_reason = "no LLM configured (set GEMINI_API_KEY or LLM_MODELS + the provider's key)"

    def _usable(self) -> list[ModelSpec]:
        now = time.monotonic()
        return [m for m in self.models if _EXHAUSTED_UNTIL.get(m.key, 0) <= now]

    @property
    def available(self) -> bool:
        return self._disabled_reason is None and bool(self._usable())

    def _throttle(self) -> None:
        wait = self._last_call + 60.0 / self._rpm - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _call(self, spec: ModelSpec, system: str, user: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        attr = PROVIDER_KEYS.get(spec.provider, "")
        chat = _chat_model(spec.provider, spec.model, getattr(self.settings, attr, "") if attr else "",
                           self.temperature)
        self._throttle()
        msg = chat.invoke([SystemMessage(system), HumanMessage(user)])
        return msg.text if hasattr(msg, "text") and isinstance(msg.text, str) else str(msg.content)

    def complete(self, system: str, user: str) -> str:
        last_error: Exception | None = None
        for spec in self._usable():
            waited = False
            for attempt in range(3):
                try:
                    return self._call(spec, system, user)
                except Exception as e:  # noqa: BLE001 - providers raise many error types
                    last_error = e
                    quota = classify_quota_error(e)
                    if quota is None:
                        if model_missing(e):
                            pkg = PROVIDER_PACKAGES.get(spec.provider, "")
                            log.warning("Model %s unavailable (%s)%s; skipping it.", spec.key,
                                        str(e).splitlines()[0][:120], f" - try: pip install {pkg}" if pkg else "")
                            _EXHAUSTED_UNTIL[spec.key] = float("inf")
                            break
                        if is_permanent(e):
                            log.warning("%s rejected the API key; skipping it.", spec.key)
                            _EXHAUSTED_UNTIL[spec.key] = float("inf")
                            break
                        if attempt == 0:
                            time.sleep(3)  # transient network/server hiccup: one quick retry
                            continue
                        break
                    kind, delay = quota
                    if kind == "minute" and not waited:
                        pause = min(delay or 30.0, MAX_QUOTA_WAIT_S)
                        self._rpm = max(2, self._rpm // 2)
                        log.info("%s per-minute limit hit; waiting %.0fs, then continuing at %d/min.",
                                 spec.key, pause, self._rpm)
                        time.sleep(pause)
                        waited = True
                        continue
                    _EXHAUSTED_UNTIL[spec.key] = time.monotonic() + (
                        _seconds_until_quota_reset() if kind == "day" else 600.0)
                    nxt = self._usable()
                    log.warning("%s quota is used up%s.%s", spec.key, " for today" if kind == "day" else " for now",
                                f" Switching to {nxt[0].key}." if nxt else
                                " No model left: falling back to the plain template.")
                    break
        raise last_error or RuntimeError("No LLM available")

    def ask_json(self, system: str, user: str) -> dict | None:
        """complete() + JSON parsing; None (caller falls back) on any failure."""
        if not self.available:
            return None
        try:
            return parse_json(self.complete(system, user))
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("Model returned unusable JSON: %s", e)
        except Exception as e:  # noqa: BLE001
            if classify_quota_error(e) is None:
                log.warning("LLM call failed, using the template instead: %s", str(e)[:200])
        return None
