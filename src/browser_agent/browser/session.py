import asyncio
import ipaddress
import math
import re
import tempfile
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from browser_agent.config import Settings
from pathlib import Path

from .dom import RESOLVE, SNAPSHOT
from .elements import score_element
from .refs import BrowserError, RefStore, StaleReferenceError
from .snapshot import normalize_element


class BrowserSession:
    def __init__(self, settings: "Settings") -> None:
        self.settings = settings
        self.refs = RefStore()
        self.state = "closed"
        self._snapshot = None
        self._temporary_profile = None
        self._page = self._context = self._browser = self._playwright = None
        self._key = "__browser_agent_" + uuid.uuid4().hex

    async def start(self) -> dict[str, Any]:
        if self.state == "started":
            return {"success": True, "state": self.state}
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        options = {
            "headless": False,
            "slow_mo": self.settings.browser_slow_mo,
            # Use the native credential store, matching the --login browser.
            # Do not remove enable-automation or spoof navigator.webdriver.
            "ignore_default_args": ["--password-store=basic", "--use-mock-keychain"],
        }
        if self.settings.browser_executable_path:
            options["executable_path"] = self.settings.browser_executable_path
        elif self.settings.browser_channel:
            options["channel"] = self.settings.browser_channel
        try:
            if self.settings.browser_persistent:
                profile = Path(self.settings.project_root) / "browser-data"
                profile.mkdir(parents=True, exist_ok=True)
                self._context = await self._playwright.chromium.launch_persistent_context(
                    str(profile), **options
                )
            else:
                self._temporary_profile = tempfile.TemporaryDirectory(
                    prefix="browser-session-", dir=self.settings.project_root
                )
                self._context = await self._playwright.chromium.launch_persistent_context(
                    self._temporary_profile.name, **options
                )
            self._context.set_default_timeout(self.settings.browser_timeout_ms)
            self._context.set_default_navigation_timeout(self.settings.navigation_timeout_ms)
            self._context.on("page", self._activate_page)
            self._activate_page(
                self._context.pages[-1] if self._context.pages else await self._context.new_page()
            )
            self.state = "started"
            return {"success": True, "state": self.state}
        except BaseException:
            await self.close()
            raise

    def _invalidate(self) -> None:
        self.refs.clear()
        self._snapshot = None

    @staticmethod
    def _public_url(url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme in {"http", "https"}:
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        return "about:blank" if url == "about:blank" else "<non-http-page>"

    @staticmethod
    def _is_private_host(hostname: str) -> bool:
        host = hostname.casefold().rstrip(".")
        if host == "localhost" or host.endswith(".localhost"):
            return True
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return any(
            (
                address.is_private,
                address.is_loopback,
                address.is_link_local,
                address.is_reserved,
                address.is_unspecified,
            )
        )

    def _activate_page(self, page):
        self._invalidate()
        self._page = page
        page.on(
            "framenavigated",
            lambda frame: (
                self._invalidate() if page is self._page and frame == page.main_frame else None
            ),
        )

    def _require_page(self):
        if self.state != "started" or self._page is None:
            raise BrowserError("Browser is not started")
        if self._page.is_closed():
            pages = [p for p in self._context.pages if not p.is_closed()]
            if not pages:
                raise BrowserError("No open browser page")
            self._activate_page(pages[-1])
        return self._page

    async def close(self) -> dict[str, Any]:
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
        finally:
            if self._playwright:
                await self._playwright.stop()
            self._page = self._context = self._browser = self._playwright = None
            self._invalidate()
            if self._temporary_profile:
                self._temporary_profile.cleanup()
                self._temporary_profile = None
            self.state = "closed"
        return {"success": True, "state": self.state}

    async def navigate(self, url: str) -> dict[str, Any]:
        parsed = urlsplit(url) if isinstance(url, str) else None
        if (
            not parsed
            or parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Use an http or https URL")
        if not getattr(self.settings, "allow_private_network", False) and self._is_private_host(
            parsed.hostname
        ):
            raise ValueError("Navigation to a private network is disabled")
        self.refs.clear()
        await self._require_page().goto(url, wait_until="domcontentloaded")
        return await self.observe()

    async def observe(self) -> dict[str, Any]:
        page = self._require_page()
        snapshot = await page.evaluate(
            SNAPSHOT,
            {
                "key": self._key,
                "epoch": uuid.uuid4().hex,
                "maxElements": self.settings.max_elements,
                "maxText": self.settings.max_text_length,
                "maxLabel": self.settings.max_element_text_length,
            },
        )
        self.refs.clear()
        epoch = snapshot.pop("epoch")
        for element in snapshot["elements"]:
            item = {
                "token": element.pop("token"),
                "version": element.pop("version"),
                "epoch": epoch,
                "page": page,
            }
            normalized = normalize_element(element, self.settings.max_element_text_length)
            element.clear()
            element.update(normalized)
            element["ref"] = self.refs.add(item)
        self._snapshot = {"success": True, **snapshot}
        return {
            "success": True,
            "url": self._public_url(snapshot["url"]),
            "title": snapshot["title"],
            "element_count": len(snapshot["elements"]),
            "text_chunk_count": len(snapshot.get("text_chunks", [])),
            "hint": "Use query_dom to retrieve only relevant text and elements.",
        }

    async def query_dom(self, query: str, limit: int = 10) -> dict[str, Any]:
        if self._snapshot is None:
            raise BrowserError("No current snapshot; observe first")
        bounded_limit = min(limit, getattr(self.settings, "max_query_results", 10))
        ranked = [(score_element(query, e), i, e) for i, e in enumerate(self._snapshot["elements"])]
        ranked.sort(key=lambda row: (-row[0], row[1]))
        elements = [{**e, "score": score} for score, _, e in ranked if score > 0][:bounded_limit]

        words = re.findall(r"\w+", query.casefold())
        chunks = self._snapshot.get("text_chunks") or [self._snapshot.get("text", "")]
        text_ranked = []
        for index, chunk in enumerate(chunks):
            folded = chunk.casefold()
            score = sum(1 for word in words if word in folded)
            if score:
                text_ranked.append((score, index, chunk))
        text_ranked.sort(key=lambda row: (-row[0], row[1]))
        max_text = getattr(self.settings, "max_query_text_length", 2000)
        text_matches = []
        used = 0
        for _, _, chunk in text_ranked[:bounded_limit]:
            remaining = max_text - used
            if remaining <= 0:
                break
            value = chunk[:remaining]
            text_matches.append(value)
            used += len(value)

        return {
            "success": True,
            "url": self._public_url(self._snapshot.get("url", "")),
            "title": self._snapshot.get("title", ""),
            "query": query,
            "elements": elements,
            "text_matches": text_matches,
        }

    async def _resolve(self, ref):
        page = self._require_page()
        item = self.refs.get(ref)
        if item["page"] is not page:
            raise StaleReferenceError("Reference belongs to a different page; observe again")
        locator = page.locator(f'[data-browser-agent-ref="{item["token"]}"]')
        if await locator.count() != 1:
            raise StaleReferenceError("Element detached or identity duplicated; observe again")
        # Resolve once to an exact node. Actions on the handle can never retarget a replacement.
        handle = await locator.element_handle()
        if handle is None or not await handle.evaluate(
            RESOLVE, {**{k: v for k, v in item.items() if k != "page"}, "key": self._key}
        ):
            if handle:
                await handle.dispose()
            raise StaleReferenceError("Element changed since observation; observe again")
        if not await handle.is_visible():
            await handle.dispose()
            raise BrowserError("Element is not visible. Run observe_page again.")
        if not await handle.is_enabled() or await handle.get_attribute("aria-disabled") == "true":
            await handle.dispose()
            raise BrowserError("Element is disabled")
        return handle

    async def _element_action(self, ref, action, *args):
        handle = await self._resolve(ref)
        try:
            await getattr(handle, action)(*args)
        finally:
            await handle.dispose()
        return {"success": True, "ref": ref}

    async def click(self, ref: str) -> dict[str, Any]:
        result = await self._element_action(ref, "click")
        # Bounded settling, never wait indefinitely for network-idle on live sites.
        await asyncio.sleep(0.1)
        return result

    async def type_text(self, ref: str, text: str, typing: bool = False) -> dict[str, Any]:
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        return await self._element_action(ref, "type" if typing else "fill", text)

    async def press(self, key: str) -> dict[str, Any]:
        await self._require_page().keyboard.press(key)
        return {"success": True}

    async def scroll(self, direction: str, amount: int) -> dict[str, Any]:
        if direction not in ("up", "down"):
            raise ValueError("direction must be up or down")
        if (
            not isinstance(amount, (int, float))
            or not math.isfinite(amount)
            or not 1 <= amount <= 5000
        ):
            raise ValueError("amount must be finite and between 1 and 5000")
        dx = amount * (-1 if direction == "left" else 1) if direction in ("left", "right") else 0
        dy = amount * (-1 if direction == "up" else 1) if direction in ("up", "down") else 0
        await self._require_page().mouse.wheel(dx, dy)
        return {"success": True}

    async def screenshot(self, full_page: bool = False) -> dict[str, Any]:
        page = self._require_page()
        directory = Path(self.settings.project_root) / "screenshots"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3] + ".png")
        while path.exists():
            await asyncio.sleep(0.001)
            path = directory / (datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3] + ".png")
        await page.screenshot(path=str(path), full_page=full_page)
        return {"success": True, "path": str(path)}

    async def back(self) -> dict[str, Any]:
        self.refs.clear()
        await self._require_page().go_back(wait_until="domcontentloaded")
        return await self.observe()

    async def get_page_text(self) -> dict[str, Any]:
        page = self._require_page()
        result = await page.evaluate(
            SNAPSHOT,
            {
                "key": self._key,
                "epoch": uuid.uuid4().hex,
                "maxElements": 0,
                "maxText": self.settings.max_text_length,
                "maxLabel": self.settings.max_element_text_length,
            },
        )
        result["success"] = True
        return {k: result[k] for k in ("success", "url", "title", "text")}

    async def scroll_into_view(self, ref: str) -> dict[str, Any]:
        return await self._element_action(ref, "scroll_into_view_if_needed")

    async def wait(self, seconds: float) -> dict[str, Any]:
        if (
            not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or not 0.1 <= seconds <= 10
        ):
            raise ValueError("seconds must be finite and between 0.1 and 10")
        self._require_page()
        await asyncio.sleep(seconds)
        return {"success": True}
