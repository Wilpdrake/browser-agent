"""Public LLM tool boundary: strict schemas, no selectors or browser internals."""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

if TYPE_CHECKING:
    from browser_agent.browser.session import BrowserSession

logger = logging.getLogger(__name__)


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Navigate(Arguments):
    url: str = Field(min_length=1, max_length=4096)

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        url = urlsplit(value)
        if url.scheme not in {"https", "http"} or not url.hostname or url.username:
            raise ValueError("Use a plain http(s) URL without credentials, not @url markup.")
        if any(c.isspace() for c in value):
            raise ValueError("Whitespace in URL is not allowed.")
        return value


class Query(Arguments):
    query: str = Field(min_length=1, max_length=500)


class Ref(Arguments):
    ref: str = Field(pattern=r"^e[1-9][0-9]*$", max_length=32)


class TypeText(Ref):
    text: str = Field(max_length=10000)
    typing: bool = False


class Press(Arguments):
    key: Literal[
        "Enter",
        "Tab",
        "Escape",
        "ArrowDown",
        "ArrowUp",
        "ArrowLeft",
        "ArrowRight",
        "Space",
        "Backspace",
        "Delete",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "Shift+Tab",
        "ControlOrMeta+A",
    ]


class Scroll(Arguments):
    direction: Literal["up", "down"]
    amount: int = Field(default=600, ge=1, le=5000)


class Screenshot(Arguments):
    full_page: bool = False


class Wait(Arguments):
    seconds: float = Field(ge=0.1, le=10)


@dataclass(frozen=True)
class Tool:
    name: str
    method: str
    description: str
    arguments: type[Arguments]


TOOLS = (
    Tool(
        "navigate_to_url",
        "navigate",
        "Navigate to an exact HTTP(S) URL. Observe afterwards.",
        Navigate,
    ),
    Tool(
        "observe_page",
        "observe",
        "Get compact page observation and NEW temporary element refs.",
        Arguments,
    ),
    Tool("query_dom", "query_dom", "Search the current snapshot locally, e.g. поле поиска.", Query),
    Tool(
        "click_element", "click", "Click an observed element. Observe again after interaction.", Ref
    ),
    Tool(
        "type_text",
        "type_text",
        "Fill a field, without Enter. typing=true uses keyboard events.",
        TypeText,
    ),
    Tool("press_key", "press", "Press a supported safe key in the focused page.", Press),
    Tool("scroll_page", "scroll", "Scroll the current page up or down by pixels.", Scroll),
    Tool("scroll_into_view", "scroll_into_view", "Scroll an observed element into view.", Ref),
    Tool(
        "take_screenshot",
        "screenshot",
        "Save a PNG locally; returns path, not vision input.",
        Screenshot,
    ),
    Tool("wait", "wait", "Wait 0.1–10 seconds for a known pending page update.", Wait),
    Tool("go_back", "back", "Go back in browser history. Observe afterwards.", Arguments),
    Tool(
        "get_page_text",
        "get_page_text",
        "Read bounded visible page text, never full HTML.",
        Arguments,
    ),
)


class ToolRegistry:
    def __init__(self, session: BrowserSession):
        self.session = session
        self._tools = {tool.name: tool for tool in TOOLS}

    def schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.arguments.model_json_schema(),
                },
            }
            for tool in TOOLS
        ]

    async def execute(self, name: str, arguments: dict) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            return {"success": False, "error": f"Unknown tool: {name}"}
        try:
            parsed = tool.arguments.model_validate(arguments)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
                for e in exc.errors(include_input=False, include_url=False)
            )
            return {"success": False, "error": f"Invalid tool arguments: {details}"}
        try:
            return await getattr(self.session, tool.method)(**parsed.model_dump())
        except (ValueError, RuntimeError, TimeoutError) as exc:
            from browser_agent.browser.refs import BrowserError

            if isinstance(exc, BrowserError):
                return {"success": False, "error": str(exc)[:1200]}
            return {
                "success": False,
                "error": f"{type(exc).__name__}: operation failed. "
                "Run observe_page before retrying.",
            }
        except Exception as exc:
            # Playwright is imported lazily so schema validation has no browser dependency.
            from playwright.async_api import Error as PlaywrightError

            if isinstance(exc, PlaywrightError):
                return {
                    "success": False,
                    "error": f"Browser {type(exc).__name__}: page or element unavailable. "
                    "Run observe_page again; do not repeat the action blindly.",
                }
            logger.error(
                "Unexpected %s in tool %s\n%s",
                type(exc).__name__,
                name,
                "".join(traceback.format_tb(exc.__traceback__)),
            )
            return {"success": False, "error": f"Unexpected {type(exc).__name__}; see error log."}
