"""Regression coverage for review findings."""

from unittest.mock import patch

import httpx
import pytest

from browser_agent.config import Settings
from browser_agent.llm.base import LLMError
from browser_agent.llm.openai_compatible import OpenAICompatibleProvider
from browser_agent.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_null_tool_calls_valid_final():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"choices": [{"message": {"content": "Done", "tool_calls": None}}]}
            )
        )
    )
    with patch("httpx.AsyncClient", return_value=client):
        provider = OpenAICompatibleProvider(Settings(llm_base_url="https://example.test/v1"))
    try:
        assert (await provider.chat([], [])).content == "Done"
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_browser_error_does_not_leak_call_log():
    from playwright.async_api import Error

    class Session:
        async def type_text(self, **kwargs):
            raise Error("Call log: password=TOPSECRET")

    result = await ToolRegistry(Session()).execute("type_text", {"ref": "e1", "text": "TOPSECRET"})
    assert result["success"] is False
    assert "TOPSECRET" not in str(result)


def test_logging_permission_error_no_traceback(capsys):
    from browser_agent.main import main

    with (
        patch("sys.argv", ["browser-agent"]),
        patch.object(Settings, "validate_llm"),
        patch("logging.basicConfig", side_effect=PermissionError("private filename")),
    ):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.asyncio
async def test_duplicate_tool_ids_rejected():
    call = {"id": "same", "function": {"name": "observe_page", "arguments": "{}"}}
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"choices": [{"message": {"tool_calls": [call, call]}}]}
            )
        )
    )
    with patch("httpx.AsyncClient", return_value=client):
        provider = OpenAICompatibleProvider(Settings(llm_base_url="https://example.test/v1"))
    try:
        with pytest.raises(LLMError, match="malformed"):
            await provider.chat([], [])
    finally:
        await provider.close()
