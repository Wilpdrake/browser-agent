import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pytest

from browser_agent.browser import BrowserError, BrowserSession, StaleReferenceError

pytestmark = pytest.mark.gui


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.settings = SimpleNamespace(
            project_root=Path(self.tmp.name),
            browser_channel="",
            browser_executable_path=os.getenv("BROWSER_EXECUTABLE_PATH")
            or shutil.which("brave")
            or "",
            browser_slow_mo=0,
            browser_persistent=True,
            max_elements=4,
            max_text_length=90,
            max_element_text_length=30,
            browser_timeout_ms=2000,
            navigation_timeout_ms=10000,
        )
        self.browser = BrowserSession(self.settings)
        await self.browser.start()

    async def asyncTearDown(self):
        await self.browser.close()
        self.tmp.cleanup()

    async def test_observation_is_bounded_and_actions_work(self):
        html = (
            "<title>Fixture</title><h1>Hello</h1>"
            '<input type="search" placeholder="Search" value="SECRET">'
            "<button onclick=\"this.textContent='Done'\">Submit</button><p>"
            + "Long text " * 40
            + "</p>"
        )
        await self.browser._page.set_content(html)
        result = await self.browser.observe()
        self.assertTrue(result["success"])
        self.assertEqual(result["title"], "Fixture")
        self.assertNotIn("text", result)
        self.assertNotIn("elements", result)
        self.assertLessEqual(result["element_count"], 4)
        self.assertNotIn("SECRET", str(result))
        found = await self.browser.query_dom("поле поиска")
        ref = found["elements"][0]["ref"]
        self.assertTrue((await self.browser.type_text(ref, "hello"))["success"])
        self.assertTrue((await self.browser.press("Tab"))["success"])
        self.assertTrue((await self.browser.scroll_into_view(ref))["success"])
        self.assertTrue((await self.browser.scroll("down", 100))["success"])
        self.assertTrue((await self.browser.wait(0.1))["success"])
        shot = await self.browser.screenshot()
        self.assertTrue(Path(shot["path"]).is_file())
        self.assertEqual(Path(shot["path"]).parent, self.settings.project_root / "screenshots")
        self.assertLessEqual(len((await self.browser.get_page_text())["text"]), 90)
        await self.browser.observe()
        button = (await self.browser.query_dom("Submit"))["elements"][0]
        await self.browser.click(button["ref"])
        await self.browser.observe()
        verified = await self.browser.query_dom("Done")
        self.assertEqual(verified["elements"][0]["text"], "Done")
        await self.browser._page.goto("about:blank")
        with self.assertRaises(StaleReferenceError):
            await self.browser.click(ref)
        self.assertTrue((await self.browser.back())["success"])

    async def test_native_roles_aria_and_hidden_elements(self):
        await self.browser._page.set_content("""
            <input type="search" aria-label="  Search   products ">
            <div role="checkbox" aria-checked="true">Chosen</div>
            <button style="display:none">Hidden</button>
            <button>  Add   one </button>""")
        await self.browser.observe()
        search = (await self.browser.query_dom("Search products"))["elements"][0]
        self.assertEqual(search["role"], "searchbox")
        self.assertEqual(search["aria_label"], "Search products")
        checkbox = (await self.browser.query_dom("checkbox"))["elements"][0]
        self.assertEqual(checkbox["role"], "checkbox")
        self.assertEqual(
            (await self.browser.query_dom("Add one"))["elements"][0]["text"], "Add one"
        )
        self.assertFalse((await self.browser.query_dom("Hidden"))["elements"])

    async def test_unrelated_modal_invalidates_previous_refs(self):
        await self.browser._page.set_content("<button>Background</button>")
        await self.browser.observe()
        ref = (await self.browser.query_dom("Background"))["elements"][0]["ref"]
        await self.browser._page.evaluate(
            "document.body.insertAdjacentHTML('beforeend', '<div role=dialog>Modal</div>')"
        )
        with self.assertRaises(StaleReferenceError):
            await self.browser.click(ref)

    async def test_identity_replacement_detachment_mutation_and_disabled(self):
        page = self.browser._page
        for mutation in (
            "const el=document.querySelector('button'); el.outerHTML=el.outerHTML",
            "document.querySelector('button').remove()",
            "document.querySelector('button').textContent = 'Changed'",
            "const b=document.querySelector('button'); b.remove(); document.body.append(b)",
        ):
            await page.set_content('<button onclick="window.didClick=true">Original</button>')
            await self.browser.observe()
            ref = (await self.browser.query_dom("Original"))["elements"][0]["ref"]
            await page.evaluate(mutation)
            with self.assertRaises(StaleReferenceError):
                await self.browser.click(ref)
            self.assertFalse(await page.evaluate("!!window.didClick"))
        await page.set_content("<button disabled>Disabled</button>")
        await self.browser.observe()
        ref = (await self.browser.query_dom("Disabled"))["elements"][0]["ref"]
        with self.assertRaises(BrowserError):
            await self.browser.click(ref)

    async def test_query_and_page_text_preserve_refs_and_typing_appends(self):
        await self.browser._page.set_content(
            '<input type="search"><input type="password" value="TOPSECRET">'
            "<textarea>HIDDENVALUE</textarea>"
        )
        observation = await self.browser.observe()
        ref = (await self.browser.query_dom("search"))["elements"][0]["ref"]
        self.assertEqual((await self.browser.query_dom("search"))["elements"][0]["ref"], ref)
        self.assertNotIn("TOPSECRET", str(observation))
        self.assertNotIn("HIDDENVALUE", str(observation))
        await self.browser.get_page_text()
        await self.browser.type_text(ref, "one")
        await self.browser.type_text(ref, "two", typing=True)
        self.assertEqual(
            await self.browser._page.locator("input[type=search]").input_value(), "onetwo"
        )
        await self.browser.observe()
        fresh = (await self.browser.query_dom("search"))["elements"][0]["ref"]
        self.assertNotEqual(ref, fresh)
        with self.assertRaises(StaleReferenceError):
            await self.browser.type_text(ref, "old")

    async def test_detached_node_can_be_reobserved_after_reattachment(self):
        page = self.browser._page
        await page.set_content("<button>Reuse me</button>")
        await self.browser.observe()
        ref = (await self.browser.query_dom("Reuse me"))["elements"][0]["ref"]
        await page.evaluate(
            'window.savedButton=document.querySelector("button"); savedButton.remove()'
        )
        await self.browser.observe()
        await page.evaluate("document.body.append(savedButton)")
        await self.browser.observe()
        fresh = (await self.browser.query_dom("Reuse me"))["elements"][0]["ref"]
        self.assertNotEqual(ref, fresh)
        await self.browser.click(fresh)

    async def test_popup_switches_internal_page_and_invalidates_refs(self):
        await self.browser._page.set_content(
            "<button onclick=\"window.open('about:blank')\">Open</button>"
        )
        old_page = self.browser._page
        await self.browser.observe()
        ref = (await self.browser.query_dom("Open"))["elements"][0]["ref"]
        async with self.browser._context.expect_page():
            await self.browser.click(ref)
        self.assertIsNot(self.browser._page, old_page)
        with self.assertRaises(StaleReferenceError):
            await self.browser.click(ref)
        await self.browser._page.close()
        await self.browser.observe()
        self.assertIs(self.browser._page, old_page)

    async def test_persistent_cookies_survive_restart(self):
        import time

        await self.browser._context.add_cookies(
            [
                {
                    "name": "demo",
                    "value": "one",
                    "domain": "example.com",
                    "path": "/",
                    "expires": time.time() + 3600,
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ]
        )
        await self.browser.close()
        await self.browser.start()
        cookies = await self.browser._context.cookies("https://example.com")
        self.assertTrue(any(c["name"] == "demo" and c["value"] == "one" for c in cookies))

    async def test_real_agent_tool_chain_with_scripted_provider(self):
        import json
        from io import StringIO

        from rich.console import Console as RichConsole

        from browser_agent.agent.agent import Agent
        from browser_agent.cli.console import Console
        from browser_agent.llm.base import LLMResponse, ToolCall
        from browser_agent.tools.registry import ToolRegistry

        await self.browser._page.set_content(
            '<input placeholder="Search">'
            "<button onclick=\"this.textContent='Verified'\">Add</button>"
        )
        original_page = self.browser._page

        class ScriptedProvider:
            step = 0

            async def chat(self, messages, tools):
                self.step += 1
                latest = json.loads(
                    next(m["content"] for m in reversed(messages) if m["role"] == "tool")
                )
                if self.step == 1:
                    return LLMResponse(
                        tool_calls=[
                            ToolCall(
                                id="find-input", name="query_dom", arguments='{"query":"Search"}'
                            )
                        ]
                    )
                if self.step == 2:
                    ref = next(e["ref"] for e in latest["elements"] if e["tag"] == "input")
                    return LLMResponse(
                        tool_calls=[
                            ToolCall(
                                id="type",
                                name="type_text",
                                arguments=json.dumps({"ref": ref, "text": "hotdog"}),
                            )
                        ]
                    )
                if self.step in (3, 6, 8):
                    return LLMResponse(
                        tool_calls=[
                            ToolCall(id=f"observe-{self.step}", name="observe_page", arguments="{}")
                        ]
                    )
                if self.step == 4:
                    return LLMResponse(
                        tool_calls=[
                            ToolCall(
                                id="find-button", name="query_dom", arguments='{"query":"Add"}'
                            )
                        ]
                    )
                if self.step == 5:
                    ref = next(e["ref"] for e in latest["elements"] if e["tag"] == "button")
                    return LLMResponse(
                        tool_calls=[
                            ToolCall(
                                id="click", name="click_element", arguments=json.dumps({"ref": ref})
                            )
                        ]
                    )
                if self.step == 7:
                    return LLMResponse(
                        tool_calls=[
                            ToolCall(
                                id="verify", name="query_dom", arguments='{"query":"Verified"}'
                            )
                        ]
                    )
                assert any(
                    "Verified" in json.loads(m["content"]).get("text_matches", [])
                    for m in messages
                    if m["role"] == "tool"
                )
                return LLMResponse(content="Verified from actual page")

        output = StringIO()
        agent = Agent(
            SimpleNamespace(max_agent_steps=10, max_history_chars=180000),
            ScriptedProvider(),
            ToolRegistry(self.browser),
            Console(RichConsole(file=output, color_system=None)),
        )
        self.assertEqual(await agent.run("Local controlled test"), "Verified from actual page")
        self.assertIs(self.browser._page, original_page)
        self.assertEqual(await original_page.locator("input").input_value(), "hotdog")
        self.assertIn("Duration:", output.getvalue())
        self.assertIn("click_element", output.getvalue())

    async def test_screenshot_timestamp_and_nonpersistent_profile_cleanup(self):
        shot = await self.browser.screenshot(full_page=True)
        self.assertRegex(Path(shot["path"]).name, r"^\d{8}-\d{6}-\d{3}\.png$")
        await self.browser.close()
        self.settings.browser_persistent = False
        await self.browser.start()
        profile = Path(self.browser._temporary_profile.name)
        self.assertEqual(profile.parent, self.settings.project_root)
        self.assertTrue(profile.is_dir())
        await self.browser.close()
        self.assertFalse(profile.exists())
        self.assertEqual(self.browser.state, "closed")
