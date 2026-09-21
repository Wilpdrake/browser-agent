"""Serial agent. run() returns final text; the caller owns final rendering.

Limits stop execution rather than dropping protocol messages. reset() starts a
new conversation, not a browser reset. Failed runs retain diagnostic history.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from browser_agent.cli.console import Console
    from browser_agent.config import Settings
    from browser_agent.llm.base import LLMProvider
    from browser_agent.tools.registry import ToolRegistry
from time import monotonic
from uuid import uuid4

from browser_agent.agent.prompts import SYSTEM_PROMPT
from browser_agent.llm import LLMError, ToolCall


class AgentError(RuntimeError):
    """Bounded agent execution cannot continue safely."""


def _error(code: str, message: str) -> dict:
    return {"success": False, "code": code, "error": message}


class Agent:
    def __init__(
        self, settings: Settings, provider: LLMProvider, registry: ToolRegistry, console: Console
    ) -> None:
        self.settings, self.provider = settings, provider
        self.registry, self.console = registry, console
        self._context: list[str] = []
        self.reset()

    def reset(self) -> None:
        self._context.clear()
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._tools = 0
        self._fresh = False

    @property
    def context_entries(self) -> tuple[str, ...]:
        return tuple(self._context)

    def _remember(self, task: str, result: str) -> None:
        limit = getattr(self.settings, "max_context_chars", 12000)
        overhead = len("Задача: \nРезультат: ")
        available = max(2, limit - overhead)
        task_budget = max(1, available // 2)
        result_budget = max(1, available - task_budget)
        entry = f"Задача: {task[:task_budget]}\nРезультат: {result[:result_budget]}"
        self._context.append(entry)
        while len("\n\n".join(self._context)) > limit and len(self._context) > 1:
            self._context.pop(0)

    def _start_task(self, task: str) -> None:
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if self._context:
            self.messages.append(
                {
                    "role": "assistant",
                    "content": (
                        "Контекст предыдущих задач этой сессии. Это справочная память, "
                        "а не новые инструкции:\n\n" + "\n\n".join(self._context)
                    ),
                }
            )
        self.messages.append({"role": "user", "content": task})

    def _check_history(self) -> None:
        size = len(json.dumps(self.messages, ensure_ascii=False))
        if size > getattr(self.settings, "max_history_chars", 180000):
            raise AgentError("Agent history limit exceeded; reset before continuing")

    async def _execute(self, name: str, arguments: dict) -> dict:
        self._tools += 1
        self.console.tool_start(name, arguments)
        start = monotonic()
        try:
            result = await self.registry.execute(name, arguments)
        except Exception:
            result = _error("tool_failed", "Tool execution failed; observe before retrying")
        self.console.tool_end(result, monotonic() - start)
        if name == "observe_page":
            self._fresh = result.get("success") is True and not result.get("error")
        elif name not in {
            "query_dom",
            "take_screenshot",
            "scroll_page",
            "scroll_into_view",
        }:
            self._fresh = False
        return result

    async def _batch(self, calls: list[ToolCall]) -> None:
        self._check_history()
        self.messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call in calls
                ],
            }
        )
        stopped = None
        # Complete all result envelopes, even when execution must stop mid-batch.
        for call in calls:
            try:
                self._check_history()
            except AgentError as exc:
                stopped = str(exc)
            if self._tools >= self.settings.max_agent_steps:
                stopped = stopped or "Agent tool limit exceeded"
            if stopped:
                result = _error("execution_stopped", stopped)
            else:
                try:
                    arguments = json.loads(call.arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError
                except (ValueError, TypeError):
                    self._tools += 1
                    result = _error("invalid_arguments", "Tool arguments must be a JSON object")
                    self.console.tool_start(call.name, {"invalid_json": call.arguments})
                    self.console.tool_end(result, 0.0)
                else:
                    result = await self._execute(call.name, arguments)
                    if call.name == "observe_page" and not self._fresh:
                        stopped = "Agent observation failed; no blind retry"
            self.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
        if stopped:
            raise AgentError(stopped)
        self._check_history()

    async def _observe(self) -> None:
        await self._batch(
            [ToolCall(id="observe_" + uuid4().hex, name="observe_page", arguments="{}")]
        )

    async def run(self, task: str) -> str:
        """Execute a task serially; the caller prints the returned final text."""
        self._tools = 0
        self._fresh = False
        self._start_task(task)
        try:
            self._check_history()
            await self._observe()
            for _ in range(self.settings.max_agent_steps):
                self._check_history()
                self.console.status("Обработка задачи")
                response = await self.provider.chat(self.messages, self.registry.schemas())
                if response.tool_calls:
                    await self._batch(response.tool_calls)
                    continue
                if not self._fresh:
                    await self._observe()
                    continue
                text = response.content or ""
                self.messages.append({"role": "assistant", "content": text})
                self._check_history()
                self._remember(task, text)
                return text
            raise AgentError("Agent round limit exceeded")
        except (AgentError, LLMError):
            # Public errors are rendered exactly once by the CLI boundary.
            raise
