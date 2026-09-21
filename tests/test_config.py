import importlib

import pytest


def settings_type():
    assert importlib.util.find_spec("browser_agent.config"), "Configuration not implemented"
    return importlib.import_module("browser_agent.config").Settings


def test_gui_required():
    from pydantic import ValidationError

    settings = settings_type()
    assert settings(_env_file=None).browser_headless is False
    with pytest.raises(ValidationError):
        settings(_env_file=None, browser_headless=True)
    assert settings(_env_file=None).allow_private_network is False


def test_gui_env_false(monkeypatch):
    monkeypatch.setenv("BROWSER_HEADLESS", "false")
    assert settings_type()(_env_file=None).browser_headless is False


def test_missing_credentials_is_clear():
    settings = settings_type()(_env_file=None, llm_base_url="", llm_model="", llm_api_key="")
    with pytest.raises(ValueError, match="LLM_BASE_URL.*LLM_API_KEY.*LLM_MODEL"):
        settings.validate_llm()


def test_remote_plain_http_llm_is_rejected_but_loopback_is_allowed():
    settings = settings_type()
    common = {"_env_file": None, "llm_model": "model", "llm_api_key": "key"}
    with pytest.raises(ValueError, match="HTTPS"):
        settings(llm_base_url="http://api.example.test/v1", **common).validate_llm()
    settings(llm_base_url="http://127.0.0.1:8080/v1", **common).validate_llm()
