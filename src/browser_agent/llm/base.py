"""Provider-neutral wire types; tool arguments remain untrusted raw JSON."""

from typing import Protocol

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=100)
    arguments: str


class LLMResponse(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class LLMError(RuntimeError):
    """Safe-to-display provider failure, without response bodies or credentials."""


class LLMProvider(Protocol):
    async def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse: ...
