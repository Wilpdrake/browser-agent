"""Human-readable logs; never render site/model strings as terminal markup."""

import json
import re

from rich.console import Console as RichConsole
from rich.panel import Panel
from rich.text import Text

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def safe(text: str) -> str:
    return _CONTROL.sub("", text)


class Console:
    def __init__(self, console: RichConsole | None = None):
        self.output = console or RichConsole()

    def status(self, text: str) -> None:
        self.output.print(Text("🤖 " + safe(text), style="cyan"))

    def tool_start(self, name: str, arguments: dict) -> None:
        self.output.rule(Text("🔧 " + safe(name)))
        self.output.print("Arguments:", style="bold")
        self.output.print_json(json.dumps(arguments, ensure_ascii=False))

    def tool_end(self, result: dict, duration: float) -> None:
        success = result.get("success", False)
        self.output.print(
            "✓ Result:" if success else "✗ Tool failed:", style="green" if success else "red"
        )
        self.output.print_json(json.dumps(result, ensure_ascii=False, default=str))
        self.output.print(f"Duration: {duration:.2f}s", style="dim")

    def final(self, text: str) -> None:
        self.output.print(Panel(Text(safe(text)), title="Результат", border_style="green"))

    def error(self, text: str) -> None:
        self.output.print(Text("✗ " + safe(text), style="red"))
