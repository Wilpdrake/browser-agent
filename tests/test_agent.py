import copy
import json
import unittest
from types import SimpleNamespace

from browser_agent.llm import LLMResponse, ToolCall


class Provider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def chat(self, messages, tools):
        self.requests.append(copy.deepcopy(messages))
        return next(self.responses)


class Registry:
    def __init__(self):
        self.calls = []

    def schemas(self):
        return []

    async def execute(self, name, arguments):
        self.calls.append((name, arguments))
        return {"success": True, "text": "observed"}


class Console:
    def __init__(self):
        self.events = []

    def __getattr__(self, name):
        return lambda *args: self.events.append((name, args))


def make_agent(responses, steps=40, history=180000, context=12000):
    from browser_agent.agent.agent import Agent

    provider, registry, console = Provider(responses), Registry(), Console()
    agent = Agent(
        SimpleNamespace(
            max_agent_steps=steps,
            max_history_chars=history,
            max_context_chars=context,
        ),
        provider,
        registry,
        console,
    )
    return agent, provider, registry, console


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_tasks_become_bounded_context_without_tool_payloads(self):
        agent, provider, registry, console = make_agent(
            [LLMResponse(content="Первый итог"), LLMResponse(content="Второй итог")]
        )

        await agent.run("Первая задача")
        await agent.run("Продолжи с учетом прошлого")

        second_request = provider.requests[1]
        context = next(
            m["content"]
            for m in second_request
            if m["role"] == "assistant" and "Контекст" in m["content"]
        )
        self.assertIn("Первая задача", context)
        self.assertIn("Первый итог", context)
        self.assertNotIn("observed", context)
        self.assertFalse(any(m["role"] == "tool" for m in second_request[:-2]))

        agent.reset()
        self.assertEqual(agent.context_entries, ())

    async def test_context_evicts_oldest_completed_tasks(self):
        agent, provider, registry, console = make_agent(
            [LLMResponse(content="A" * 30), LLMResponse(content="B" * 30)], context=90
        )
        await agent.run("old-task-" + "x" * 30)
        await agent.run("new-task-" + "y" * 30)

        self.assertNotIn("old-task", "\n".join(agent.context_entries))
        self.assertIn("new-task", "\n".join(agent.context_entries))

    async def test_initial_observation_precedes_final_and_reset(self):
        agent, provider, registry, console = make_agent([LLMResponse(content="Done")])
        self.assertEqual(await agent.run("Read page"), "Done")
        self.assertEqual(registry.calls, [("observe_page", {})])
        messages = provider.requests[0]
        self.assertEqual(messages[-1]["role"], "tool")
        self.assertEqual(messages[-1]["tool_call_id"], messages[-2]["tool_calls"][0]["id"])
        self.assertEqual([event for event in console.events if event[0] == "final"], [])
        agent.reset()
        self.assertEqual(len(agent.messages), 1)

    async def test_action_is_verified_before_final_and_reasoning_never_printed(self):
        agent, provider, registry, console = make_agent(
            [
                LLMResponse(
                    content="PRIVATE reasoning",
                    tool_calls=[ToolCall(id="click1", name="click", arguments='{"ref":"e1"}')],
                ),
                LLMResponse(content="premature"),
                LLMResponse(content="Verified"),
            ]
        )
        self.assertEqual(await agent.run("Click"), "Verified")
        self.assertEqual(
            [name for name, args in registry.calls], ["observe_page", "click", "observe_page"]
        )
        self.assertNotIn("PRIVATE", repr(console.events))
        self.assertNotIn("premature", repr(console.events))
        tools = [m for m in provider.requests[-1] if m["role"] == "tool"]
        self.assertEqual(tools[1]["tool_call_id"], "click1")

    async def test_malformed_arguments_become_structured_tool_error(self):
        agent, provider, registry, console = make_agent(
            [
                LLMResponse(tool_calls=[ToolCall(id="bad", name="click", arguments="[1]")]),
                LLMResponse(content="Cannot click"),
            ]
        )
        await agent.run("Click")
        self.assertEqual(len(registry.calls), 1)
        result = json.loads(provider.requests[-1][-1]["content"])
        self.assertFalse(result["success"])
        self.assertEqual(result["code"], "invalid_arguments")
        logged = [event for event in console.events if event[0] == "tool_end"]
        self.assertTrue(any(not event[1][0].get("success", True) for event in logged))

    async def test_tool_budget_caps_batches_and_keeps_protocol_complete(self):
        from browser_agent.agent import AgentError

        agent, provider, registry, console = make_agent(
            [
                LLMResponse(
                    tool_calls=[ToolCall(id=str(i), name="click", arguments="{}") for i in range(5)]
                )
            ],
            steps=2,
        )
        with self.assertRaisesRegex(AgentError, "limit"):
            await agent.run("Click")
        self.assertLessEqual(len(registry.calls), 2)
        requested = [c["id"] for m in agent.messages for c in m.get("tool_calls", [])]
        results = [m["tool_call_id"] for m in agent.messages if m["role"] == "tool"]
        self.assertEqual(requested, results)

    async def test_history_limit_stops_without_truncating(self):
        from browser_agent.agent import AgentError

        agent, provider, registry, console = make_agent([], history=100)
        with self.assertRaisesRegex(AgentError, "history"):
            await agent.run("x" * 200)
        self.assertFalse(provider.requests)
        self.assertFalse(registry.calls)

    async def test_failed_observation_never_allows_success_or_blind_retry(self):
        from browser_agent.agent import AgentError

        agent, provider, registry, console = make_agent([LLMResponse(content="false success")])

        async def fail(name, args):
            registry.calls.append((name, args))
            return {"success": False, "error": {"code": "broken"}}

        registry.execute = fail
        with self.assertRaisesRegex(AgentError, "observation"):
            await agent.run("Read")
        self.assertEqual(len(registry.calls), 1)
        self.assertFalse(provider.requests)

    async def test_empty_observation_is_not_success(self):
        from browser_agent.agent import AgentError

        agent, provider, registry, console = make_agent([LLMResponse(content="false success")])

        async def empty(name, arguments):
            return {}

        registry.execute = empty
        with self.assertRaises(AgentError):
            await agent.run("Read")
        self.assertFalse(provider.requests)

    async def test_round_budget_counts_invalid_calls(self):
        from browser_agent.agent import AgentError

        response = LLMResponse(tool_calls=[ToolCall(id="bad", name="click", arguments="{")])
        agent, provider, registry, console = make_agent([response] * 10, steps=2)
        with self.assertRaisesRegex(AgentError, "limit"):
            await agent.run("Read")
        self.assertLessEqual(len(provider.requests), 2)

    async def test_explicit_observation_after_action_needs_no_extra_final_loop(self):
        agent, provider, registry, console = make_agent(
            [
                LLMResponse(
                    tool_calls=[
                        ToolCall(id="action", name="click_element", arguments='{"ref":"e1"}'),
                        ToolCall(id="verify", name="observe_page", arguments="{}"),
                    ]
                ),
                LLMResponse(content="Verified"),
            ]
        )
        self.assertEqual(await agent.run("Click"), "Verified")
        self.assertEqual(
            [name for name, args in registry.calls],
            ["observe_page", "click_element", "observe_page"],
        )
        self.assertEqual(len(provider.requests), 2)

    async def test_read_only_query_preserves_fresh_observation(self):
        agent, provider, registry, console = make_agent(
            [
                LLMResponse(
                    tool_calls=[
                        ToolCall(id="query", name="query_dom", arguments='{"query":"price"}')
                    ]
                ),
                LLMResponse(content="Read from targeted result"),
            ]
        )

        self.assertEqual(await agent.run("Read price"), "Read from targeted result")
        self.assertEqual(
            [name for name, args in registry.calls],
            ["observe_page", "query_dom"],
        )
        self.assertEqual(len(provider.requests), 2)

    async def test_real_registry_observation_name_contract(self):
        from browser_agent.tools.registry import ToolRegistry

        agent, provider, registry, console = make_agent([LLMResponse(content="Read")])

        class Session:
            async def observe(self):
                return {"success": True, "text": "page"}

        agent.registry = ToolRegistry(Session())
        self.assertEqual(await agent.run("Read"), "Read")
        self.assertEqual(json.loads(provider.requests[0][-1]["content"])["text"], "page")

    async def test_registry_exception_is_structured_and_not_printed_raw(self):
        agent, provider, registry, console = make_agent(
            [
                LLMResponse(tool_calls=[ToolCall(id="bad", name="click", arguments="{}")]),
                LLMResponse(content="Failed"),
                LLMResponse(content="Failed"),
            ]
        )
        original = registry.execute

        async def fail(name, args):
            if name == "click":
                raise RuntimeError("SECRET RAW")
            return await original(name, args)

        registry.execute = fail
        self.assertEqual(await agent.run("Click"), "Failed")
        self.assertNotIn("SECRET RAW", repr(console.events))
