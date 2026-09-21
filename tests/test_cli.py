import asyncio
import importlib.util
import os
import subprocess
import sys
from io import BytesIO, StringIO

import pytest


def test_terminal_reader_decodes_one_line_at_a_time():
    from browser_agent.main import read_terminal_line

    stdin = BytesIO(b"bad\xd0x\n" + "Прочитай почту\n".encode())
    stdout = StringIO()

    with pytest.raises(UnicodeDecodeError):
        read_terminal_line("> ", stdin=stdin, stdout=stdout)

    assert read_terminal_line("> ", stdin=stdin, stdout=stdout) == "Прочитай почту"


def test_command_input_recovers_from_invalid_terminal_bytes():
    from browser_agent.main import read_command

    values = iter(
        [
            UnicodeDecodeError("utf-8", b"bad\xd0x", 3, 4, "invalid continuation byte"),
            "Прочитай почту",
        ]
    )
    errors = []

    def read(_prompt):
        value = next(values)
        if isinstance(value, Exception):
            raise value
        return value

    class Console:
        def error(self, message):
            errors.append(message)

    assert asyncio.run(read_command(Console(), read=read)) == "Прочитай почту"
    assert errors


def test_cli_missing_credentials_no_traceback():
    assert importlib.util.find_spec("browser_agent.__main__"), "CLI not implemented"
    env = dict(os.environ, LLM_BASE_URL="", LLM_API_KEY="", LLM_MODEL="")
    result = subprocess.run(
        [sys.executable, "-m", "browser_agent", "--task", "test"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 2
    assert "LLM_BASE_URL" in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_console_treats_page_text_as_literal():
    assert importlib.util.find_spec("browser_agent.cli"), "Console not implemented"
    from io import StringIO

    from rich.console import Console as RichConsole

    from browser_agent.cli.console import Console

    stream = StringIO()
    console = Console(RichConsole(file=stream, color_system=None))
    console.final("[red]untrusted[/red]")
    assert "[red]untrusted[/red]" in stream.getvalue()


def test_console_redacts_typed_text():
    from rich.console import Console as RichConsole

    from browser_agent.cli.console import Console

    stream = StringIO()
    console = Console(RichConsole(file=stream, color_system=None))
    console.tool_start("type_text", {"ref": "e1", "text": "TOPSECRET", "typing": False})

    rendered = stream.getvalue()
    assert "TOPSECRET" not in rendered
    assert "[REDACTED" in rendered
