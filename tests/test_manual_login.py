"""Manual login must never launch through Playwright or require an LLM."""

import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

from browser_agent.config import Settings


def test_login_handoff_stops_automation_and_restarts_it_after_manual_browser_closes():
    from browser_agent.main import manual_login_handoff

    events = []

    class Session:
        async def close(self):
            events.append("automation-stopped")

        async def start(self):
            events.append("automation-restarted")

    def login(_settings, _console):
        events.append("manual-browser")
        return 0

    result = asyncio.run(manual_login_handoff(Session(), object(), object(), login=login))

    assert result is True
    assert events == ["automation-stopped", "manual-browser", "automation-restarted"]


def test_manual_login_command_has_only_dedicated_profile():
    assert importlib.util.find_spec("browser_agent.browser.manual"), "Manual login missing"
    from browser_agent.browser.manual import login_command

    root = Path(__file__).resolve().parents[1]
    settings = Settings(project_root=root, browser_executable_path="/usr/bin/brave")
    command = login_command(settings)
    assert command[0] == "/usr/bin/brave"
    assert f"--user-data-dir={root / 'browser-data'}" in command
    assert "https://accounts.google.com/" in command
    assert not any("automation" in arg or "debugging" in arg or "sandbox" in arg for arg in command)


def test_login_does_not_require_api_credentials():
    import browser_agent.main as cli

    with (
        patch("sys.argv", ["browser-agent", "--login"]),
        patch("browser_agent.browser.manual.manual_login", return_value=0) as login,
    ):
        with pytest.raises(SystemExit) as exc:
            cli.main()
    assert exc.value.code == 0
    login.assert_called_once()
