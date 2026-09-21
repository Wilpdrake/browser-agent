import copy
from types import SimpleNamespace

import pytest

from browser_agent.browser.session import BrowserSession


class FakePage:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def is_closed(self):
        return False

    async def evaluate(self, _script, _arguments):
        return copy.deepcopy(self.snapshot)


@pytest.mark.asyncio
async def test_observe_returns_overview_without_page_body_or_all_elements():
    settings = SimpleNamespace(
        max_elements=100,
        max_text_length=6000,
        max_element_text_length=200,
        max_query_results=5,
        max_query_text_length=500,
    )
    session = BrowserSession(settings)
    session.state = "started"
    session._page = FakePage(
        {
            "epoch": "epoch",
            "url": "https://shop.example/catalog?token=SECRET#private",
            "title": "Shop",
            "headings": [{"text": "Catalog"}],
            "text": "secret full page body",
            "text_chunks": ["Product alpha", "Checkout summary"],
            "elements": [
                {
                    "token": "token-1",
                    "version": 0,
                    "tag": "button",
                    "type": "",
                    "role": "button",
                    "text": "Checkout",
                    "aria_label": None,
                    "label": "",
                    "placeholder": "",
                    "name": "",
                    "checked": None,
                    "disabled": False,
                }
            ],
        }
    )

    result = await session.observe()

    assert result == {
        "success": True,
        "url": "https://shop.example/catalog",
        "title": "Shop",
        "element_count": 1,
        "text_chunk_count": 2,
        "hint": "Use query_dom to retrieve only relevant text and elements.",
    }
    assert "text" not in result
    assert "elements" not in result


@pytest.mark.asyncio
async def test_query_dom_returns_only_ranked_bounded_matches():
    settings = SimpleNamespace(
        max_query_results=1,
        max_query_text_length=30,
    )
    session = BrowserSession(settings)
    session._snapshot = {
        "success": True,
        "url": "https://shop.example?token=SECRET#private",
        "title": "Shop",
        "headings": [],
        "text": "must never be returned",
        "text_chunks": [
            "Unrelated catalog introduction",
            "Checkout total is 10 dollars",
            "Checkout delivery is tomorrow",
        ],
        "elements": [
            {"ref": "e1", "tag": "button", "role": "button", "text": "Checkout"},
            {"ref": "e2", "tag": "button", "role": "button", "text": "Cancel checkout"},
        ],
    }

    result = await session.query_dom("checkout", limit=50)

    assert result["success"] is True
    assert result["url"] == "https://shop.example"
    assert result["query"] == "checkout"
    assert len(result["elements"]) == 1
    assert result["elements"][0]["ref"] == "e1"
    assert len(result["text_matches"]) == 1
    assert "Checkout" in result["text_matches"][0]
    assert len(result["text_matches"][0]) <= 30
    assert "text" not in result
    assert "must never be returned" not in str(result)
    assert "SECRET" not in str(result)
