"""Validated environment configuration; all writable state belongs to this project."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    project_root: Path = PROJECT_ROOT
    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    llm_provider: str = "openai-compatible"
    llm_timeout_seconds: float = Field(default=90, ge=1, le=300)
    browser_channel: str = ""
    browser_executable_path: str = ""
    browser_headless: Literal[False] = False
    browser_slow_mo: int = Field(default=150, ge=0, le=2000)
    browser_persistent: bool = True
    allow_private_network: bool = False
    browser_timeout_ms: int = Field(default=10000, ge=100, le=120000)
    navigation_timeout_ms: int = Field(default=30000, ge=100, le=120000)
    max_elements: int = Field(default=100, ge=1, le=500)
    max_text_length: int = Field(default=6000, ge=100, le=30000)
    max_element_text_length: int = Field(default=200, ge=10, le=1000)
    max_query_results: int = Field(default=10, ge=1, le=50)
    max_query_text_length: int = Field(default=2000, ge=100, le=10000)
    max_agent_steps: int = Field(default=40, ge=1, le=200)
    max_history_chars: int = Field(default=180000, ge=10000, le=1000000)
    max_context_chars: int = Field(default=12000, ge=1000, le=100000)

    @field_validator("browser_headless", mode="before")
    @classmethod
    def gui_only(cls, value: object) -> object:
        if isinstance(value, str) and value.lower() in {"false", "0", "no", "off"}:
            return False
        return value

    def validate_llm(self) -> None:
        missing = [
            name
            for name, value in (
                ("LLM_BASE_URL", self.llm_base_url.strip()),
                ("LLM_API_KEY", self.llm_api_key.get_secret_value().strip()),
                ("LLM_MODEL", self.llm_model.strip()),
            )
            if not value
        ]
        if missing:
            raise ValueError("LLM не настроен. Заполните .env: " + ", ".join(missing))
        if self.llm_provider != "openai-compatible":
            raise ValueError(
                "Неизвестный LLM_PROVIDER. Доступен openai-compatible; "
                "для другого протокола добавьте реализацию LLMProvider."
            )
        parsed = urlsplit(self.llm_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("LLM_BASE_URL должен быть HTTP(S) URL без встроенных credentials.")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError(
                "Удаленный LLM_BASE_URL должен использовать HTTPS; "
                "HTTP разрешен только для loopback."
            )
