import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from pydantic import SecretStr


def settings():
    return SimpleNamespace(
        llm_base_url="https://example.test/v1/",
        llm_api_key=SecretStr("secret"),
        llm_model="test-model",
        llm_timeout_seconds=12,
    )


class LLMTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_preserves_tool_json_ignores_reasoning_and_closes(self):
        from browser_agent.llm import OpenAICompatibleProvider

        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "reasoning_content": "PRIVATE",
                                "tool_calls": [
                                    {
                                        "id": "a",
                                        "type": "function",
                                        "function": {"name": "observe", "arguments": "{ broken"},
                                    }
                                ],
                            }
                        }
                    ]
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch("httpx.AsyncClient", return_value=client):
            provider = OpenAICompatibleProvider(settings())
        response = await provider.chat([{"role": "user", "content": "hello"}], [])
        self.assertIsNone(response.content)
        self.assertEqual(response.tool_calls[0].arguments, "{ broken")
        self.assertNotIn("PRIVATE", response.model_dump_json())
        self.assertEqual(str(requests[0].url), "https://example.test/v1/chat/completions")
        self.assertEqual(json.loads(requests[0].content)["model"], "test-model")
        await provider.close()
        self.assertTrue(client.is_closed)

    async def test_failures_are_safe_meaningful_errors(self):
        from browser_agent.llm import LLMError, OpenAICompatibleProvider

        cases = [
            (401, {"error": "secret PRIVATE"}, "HTTP 401"),
            (200, {"choices": []}, "malformed"),
            (200, {"choices": [{"message": {"content": 12}}]}, "malformed"),
        ]
        for status, body, expected in cases:
            with self.subTest(status=status, body=body):
                client = httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        lambda r, status=status, body=body: httpx.Response(status, json=body)
                    )
                )
                with patch("httpx.AsyncClient", return_value=client):
                    provider = OpenAICompatibleProvider(settings())
                with self.assertRaisesRegex(LLMError, expected) as error:
                    await provider.chat([], [])
                self.assertNotIn("secret", str(error.exception))
                await provider.close()

    async def test_network_timeout_is_sanitized(self):
        from browser_agent.llm import LLMError, OpenAICompatibleProvider

        def fail(request):
            raise httpx.ReadTimeout("secret PRIVATE", request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
        with patch("httpx.AsyncClient", return_value=client) as factory:
            provider = OpenAICompatibleProvider(settings())
        self.assertEqual(factory.call_args.kwargs["timeout"], 12)
        with self.assertRaisesRegex(LLMError, "network|timeout") as error:
            await provider.chat([], [])
        self.assertNotIn("secret", str(error.exception))
        await provider.close()
