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
        self.assertLessEqual(len(result["text"]), 90)
        self.assertLessEqual(len(result["elements"]), 4)
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
        button = (
            next(e for e in found["elements"] if e["tag"] == "button")
            if any(e["tag"] == "button" for e in found["elements"])
            else next(e for e in (await self.browser.observe())["elements"] if e["tag"] == "button")
        )
        await self.browser.click(button["ref"])
        self.assertIn("Done", (await self.browser.observe())["text"])
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
        elements = (await self.browser.observe())["elements"]
        self.assertEqual(elements[0]["role"], "searchbox")
        self.assertEqual(elements[0]["aria_label"], "Search products")
        self.assertTrue(any(e["role"] == "checkbox" for e in elements))
        self.assertEqual(elements[-1]["text"], "Add one")
        self.assertFalse(any(e["text"] == "Hidden" for e in elements))

    async def test_unrelated_modal_invalidates_previous_refs(self):
        await self.browser._page.set_content("<button>Background</button>")
        ref = (await self.browser.observe())["elements"][0]["ref"]
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
            ref = (await self.browser.observe())["elements"][0]["ref"]
            await page.evaluate(mutation)
            with self.assertRaises(StaleReferenceError):
                await self.browser.click(ref)
            self.assertFalse(await page.evaluate("!!window.didClick"))
        await page.set_content("<button disabled>Disabled</button>")
        ref = (await self.browser.observe())["elements"][0]["ref"]
        with self.assertRaises(BrowserError):
            await self.browser.click(ref)

    async def test_query_and_page_text_preserve_refs_and_typing_appends(self):
        await self.browser._page.set_content(
            '<input type="search"><input type="password" value="TOPSECRET">'
            "<textarea>HIDDENVALUE</textarea>"
        )
        observation = await self.browser.observe()
        ref = observation["elements"][0]["ref"]
        self.assertEqual((await self.browser.query_dom("search"))["elements"][0]["ref"], ref)
        self.assertNotIn("TOPSECRET", str(observation))
        self.assertNotIn("HIDDENVALUE", str(observation))
        await self.browser.get_page_text()
        await self.browser.type_text(ref, "one")
        await self.browser.type_text(ref, "two", typing=True)
        self.assertEqual(
            await self.browser._page.locator("input[type=search]").input_value(), "onetwo"
        )
        fresh = (await self.browser.observe())["elements"][0]["ref"]
        self.assertNotEqual(ref, fresh)
        with self.assertRaises(StaleReferenceError):
            await self.browser.type_text(ref, "old")

    async def test_detached_node_can_be_reobserved_after_reattachment(self):
        page = self.browser._page
        await page.set_content("<button>Reuse me</button>")
        ref = (await self.browser.observe())["elements"][0]["ref"]
        await page.evaluate(
            'window.savedButton=document.querySelector("button"); savedButton.remove()'
        )
        await self.browser.observe()
        await page.evaluate("document.body.append(savedButton)")
        fresh = (await self.browser.observe())["elements"][0]["ref"]
        self.assertNotEqual(ref, fresh)
        await self.browser.click(fresh)

    async def test_popup_switches_internal_page_and_invalidates_refs(self):
        await self.browser._page.set_content(
            "<button onclick=\"window.open('about:blank')\">Open</button>"
        )
        old_page = self.browser._page
        ref = (await self.browser.observe())["elements"][0]["ref"]
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
                observation = next(
                    json.loads(m["content"])
                    for m in reversed(messages)
                    if m["role"] == "tool" and "elements" in m["content"]
                )
                if self.step in (2, 4):
                    return LLMResponse(
                        tool_calls=[
                            ToolCall(id=str(self.step), name="observe_page", arguments="{}")
                        ]
                    )
                if self.step == 1:
                    ref = next(e["ref"] for e in observation["elements"] if e["tag"] == "input")
                    return LLMResponse(
                        tool_calls=[
                            ToolCall(
                                id="type",
                                name="type_text",
                                arguments=json.dumps({"ref": ref, "text": "hotdog"}),
                            )
                        ]
                    )
                if self.step == 3:
                    ref = next(e["ref"] for e in observation["elements"] if e["tag"] == "button")
                    return LLMResponse(
                        tool_calls=[
                            ToolCall(
                                id="click", name="click_element", arguments=json.dumps({"ref": ref})
                            )
                        ]
                    )
                assert "Verified" in observation["text"]
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
