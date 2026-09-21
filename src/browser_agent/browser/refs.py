"""Monotonic, session-local references; clearing never resets the counter."""

from typing import Any


class BrowserError(RuntimeError):
    """Expected browser operation failure."""


class StaleReferenceError(BrowserError):
    """Observe again: the referenced DOM identity is no longer valid."""


class RefStore:
    def __init__(self) -> None:
        self._next = 0
        self._items: dict[str, dict[str, Any]] = {}

    def add(self, item: dict[str, Any]) -> str:
        self._next += 1
        ref = f"e{self._next}"
        self._items[ref] = item
        return ref

    def clear(self) -> None:
        self._items.clear()

    def get(self, ref: str) -> dict[str, Any]:
        try:
            return self._items[ref]
        except (KeyError, TypeError) as exc:
            raise StaleReferenceError(
                f"Unknown or expired reference: {ref}; observe again"
            ) from exc
