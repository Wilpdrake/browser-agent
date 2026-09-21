"""Real GUI smoke: .venv/bin/python scripts/browser_smoke.py.

On NixOS set PLAYWRIGHT_NODEJS_PATH to a working system node executable.
Set BROWSER_EXECUTABLE_PATH for Brave; normal Settings/.env are respected.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from browser_agent.browser import BrowserSession
from browser_agent.config import Settings


async def main() -> None:
    browser = BrowserSession(Settings())
    try:
        await browser.start()
        observation = await browser.navigate("https://example.com")
        assert observation["title"] == "Example Domain", observation["title"]
        shot = await browser.screenshot()
        cdp = await browser._context.new_cdp_session(browser._page)
        window = await cdp.send("Browser.getWindowForTarget")
        await cdp.detach()
        print("GUI window:", json.dumps(window["bounds"]))
        print(
            json.dumps(
                {"observation": observation, "title": observation["title"], "screenshot": shot},
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
