"""Deterministic local ranking; never send a full DOM to an LLM."""

import re
from typing import Any


def score_element(query: str, element: dict[str, Any]) -> int:
    words = re.findall(r"\w+", query.casefold())
    text = " ".join(
        str(element.get(k, ""))
        for k in ("tag", "type", "role", "label", "text", "placeholder", "name")
    ).casefold()
    score = sum(2 for word in words if word in text)
    search = ("search", "find", "поиск", "искать", "найти")
    if any(any(s in w for s in search) for w in words) and any(s in text for s in search):
        score += 10
    if any(w in ("field", "box", "input", "поле", "ввод") for w in words) and element.get(
        "tag"
    ) in ("input", "textarea"):
        score += 3
    return score
