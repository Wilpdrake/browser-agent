"""Small asynchronous OpenAI-compatible chat client; never logs raw responses."""

import asyncio

import httpx

from browser_agent.config import Settings

from .base import LLMError, LLMResponse, ToolCall


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.url = settings.llm_base_url.rstrip("/") + "/chat/completions"
        self.timeout = float(settings.llm_timeout_seconds)
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            headers={"Authorization": "Bearer " + settings.llm_api_key.get_secret_value()},
        )

    async def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        payload = {"model": self.settings.llm_model, "messages": messages}
        if tools:
            payload["tools"] = tools
        try:
            async with asyncio.timeout(self.timeout):
                response = await self.client.post(self.url, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"LLM HTTP {exc.response.status_code}") from None
        except (httpx.RequestError, TimeoutError):
            raise LLMError("LLM network failure or timeout") from None
        try:
            message = response.json()["choices"][0]["message"]
            raw_calls = message.get("tool_calls")
            if raw_calls is None:
                raw_calls = []
            if not isinstance(raw_calls, list):
                raise ValueError("tool_calls must be a list")
            calls = [
                ToolCall(
                    id=call["id"],
                    name=call["function"]["name"],
                    arguments=call["function"]["arguments"],
                )
                for call in raw_calls
            ]
            if len({call.id for call in calls}) != len(calls):
                raise ValueError("duplicate tool call IDs")
            return LLMResponse(content=message.get("content"), tool_calls=calls)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise LLMError("LLM returned a malformed chat response") from None

    async def close(self) -> None:
        await self.client.aclose()
