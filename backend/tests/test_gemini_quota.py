"""LLM model list (LangChain): per-minute waits, daily-quota fallbacks, missing models, providers."""
import pytest

from jobscout import llm as llm_mod
from jobscout.llm import LLM, ModelSpec, classify_quota_error, parse_json, parse_models

DAY_429 = ("GoogleRateLimitError: Error calling model 'gemini-3.5-flash' (RESOURCE_EXHAUSTED): 429 "
           "RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota', "
           "'details': [{'violations': [{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}, "
           "{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '41s'}]}}")
MIN_429 = ("429 RESOURCE_EXHAUSTED {'details': [{'violations': [{'quotaId': "
           "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}]}, {'retryDelay': '7s'}]}")
OPENAI_RPM = "RateLimitError: Error code: 429 - Rate limit reached for gpt. Please try again in 20s."
OPENAI_QUOTA = "RateLimitError: Error code: 429 - {'error': {'code': 'insufficient_quota'}}"


def test_classify_across_providers():
    assert classify_quota_error(Exception(DAY_429)) == ("day", 41.0)
    assert classify_quota_error(Exception(MIN_429)) == ("minute", 7.0)
    assert classify_quota_error(Exception(OPENAI_RPM)) == ("minute", 20.0)
    assert classify_quota_error(Exception(OPENAI_QUOTA))[0] == "day"
    assert classify_quota_error(Exception("500 INTERNAL")) is None


def test_parse_models(monkeypatch):
    from jobscout.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "llm_models", "")
    monkeypatch.setattr(s, "gemini_model", "g1")
    monkeypatch.setattr(s, "gemini_fallback_models", "g2, g3")
    assert [m.key for m in parse_models(s)] == ["google_genai:g1", "google_genai:g2", "google_genai:g3"]
    monkeypatch.setattr(s, "llm_models", "openai:gpt-x, groq:llama, bare-gemini")
    assert parse_models(s) == [ModelSpec("openai", "gpt-x"), ModelSpec("groq", "llama"),
                               ModelSpec("google_genai", "bare-gemini")]


def test_models_without_keys_are_skipped(monkeypatch):
    from jobscout.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "llm_models", "openai:gpt-x,google_genai:g1,ollama:llama3")
    monkeypatch.setattr(s, "openai_api_key", "")
    monkeypatch.setattr(s, "gemini_api_key", "k")
    assert [m.key for m in LLM().models] == ["google_genai:g1", "ollama:llama3"]  # ollama needs no key


def test_parse_json_tolerates_fences_and_prose():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": 2} hope that helps') == {"a": 2}


@pytest.fixture
def model(monkeypatch):
    from jobscout.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "llm_models", "google_genai:main,google_genai:lite1,groq:lite2")
    monkeypatch.setattr(s, "gemini_api_key", "x")
    monkeypatch.setattr(s, "groq_api_key", "y")
    monkeypatch.setattr(llm_mod, "_EXHAUSTED_UNTIL", {})
    sleeps = []
    monkeypatch.setattr(llm_mod.time, "sleep", lambda sec: sleeps.append(sec))
    m = LLM()
    m._rpm = 10_000
    return m, sleeps


def _script(monkeypatch, m, plan):
    def fake_call(spec, system, user):
        exp, outcome = plan.pop(0)
        assert spec.model == exp, (spec.model, exp)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(m, "_call", fake_call)


def test_daily_quota_switches_model_and_is_remembered(model, monkeypatch):
    m, _ = model
    _script(monkeypatch, m, [("main", Exception(DAY_429)), ("lite1", "a"), ("lite1", "b")])
    assert m.complete("s", "u") == "a"
    assert m.complete("s", "u") == "b"
    assert "google_genai:main" not in [x.key for x in LLM()._usable()]  # shared across jobs


def test_per_minute_limit_waits_then_retries(model, monkeypatch):
    m, sleeps = model
    _script(monkeypatch, m, [("main", Exception(MIN_429)), ("main", "ok")])
    assert m.complete("s", "u") == "ok" and 7.0 in sleeps


def test_other_provider_used_when_gemini_exhausted(model, monkeypatch):
    m, _ = model
    _script(monkeypatch, m, [("main", Exception(DAY_429)), ("lite1", Exception(DAY_429)), ("lite2", "groq!")])
    assert m.complete("s", "u") == "groq!"


def test_all_used_up_returns_none_and_stops_trying(model, monkeypatch):
    m, _ = model
    _script(monkeypatch, m, [("main", Exception(DAY_429)), ("lite1", Exception(DAY_429)),
                             ("lite2", Exception(OPENAI_QUOTA))])
    assert m.ask_json("s", "u") is None
    assert not m.available


def test_missing_model_or_package_is_skipped(model, monkeypatch):
    m, _ = model
    _script(monkeypatch, m, [("main", Exception("404 NOT_FOUND model")), ("lite1", '{"x": 1}')])
    assert m.ask_json("s", "u") == {"x": 1}
