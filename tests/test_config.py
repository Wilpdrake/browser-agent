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


def test_gui_env_false(monkeypatch):
    monkeypatch.setenv("BROWSER_HEADLESS", "false")
    assert settings_type()(_env_file=None).browser_headless is False


def test_missing_credentials_is_clear():
    settings = settings_type()(_env_file=None, llm_base_url="", llm_model="", llm_api_key="")
    with pytest.raises(ValueError, match="LLM_BASE_URL.*LLM_API_KEY.*LLM_MODEL"):
        settings.validate_llm()
