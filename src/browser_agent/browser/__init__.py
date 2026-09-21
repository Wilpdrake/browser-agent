"""GUI browser automation with bounded observations and identity-safe refs."""

from .elements import score_element
from .refs import BrowserError, RefStore, StaleReferenceError
from .session import BrowserSession

__all__ = ["BrowserSession", "BrowserError", "StaleReferenceError", "RefStore", "score_element"]
