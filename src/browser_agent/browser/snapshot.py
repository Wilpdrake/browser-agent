"""Defensive normalization of the already bounded DOM wire representation."""

import re
from typing import Any

TEXT_FIELDS = ("tag", "role", "text", "type", "aria_label", "label", "placeholder", "name")


def normalize_element(element: dict[str, Any], max_length: int) -> dict[str, Any]:
    result = {
        field: (
            re.sub(r"\s+", " ", str(element[field])).strip()[:max_length]
            if element.get(field) is not None
            else None
        )
        for field in TEXT_FIELDS
    }
    result["disabled"] = element.get("disabled") is True
    result["checked"] = (
        element.get("checked")
        if element.get("checked") in (True, False, None, "true", "false", "mixed")
        else None
    )
    return result
