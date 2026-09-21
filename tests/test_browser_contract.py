import unittest
from types import SimpleNamespace

from browser_agent.browser import BrowserSession


class ContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_http_urls_rejected_before_start(self):
        browser = BrowserSession(SimpleNamespace())
        for url in (
            "data:text/html,hi",
            "about:blank",
            "https://",
            "https://user:password@example.com",
        ):
            with self.assertRaises(ValueError):
                await browser.navigate(url)

    async def test_query_uses_cached_snapshot(self):
        browser = BrowserSession(SimpleNamespace())
        browser._snapshot = {
            "success": True,
            "elements": [{"ref": "e1", "tag": "input", "type": "search"}],
        }
        result = await browser.query_dom("поиск")
        self.assertEqual(result["elements"][0]["ref"], "e1")

    async def test_wait_scroll_limits_validated_before_browser(self):
        browser = BrowserSession(SimpleNamespace())
        for seconds in (0, 11, float("nan")):
            with self.assertRaises(ValueError):
                await browser.wait(seconds)
        for direction, amount in (("left", 10), ("down", 0), ("up", 5001)):
            with self.assertRaises(ValueError):
                await browser.scroll(direction, amount)
