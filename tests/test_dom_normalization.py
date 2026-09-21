import importlib


def test_dom_normalization_bounds_and_drops_input_values():
    assert importlib.util.find_spec("browser_agent.browser.snapshot"), "Normalizer missing"
    from browser_agent.browser.snapshot import normalize_element

    item = normalize_element(
        {
            "tag": "input",
            "role": "searchbox",
            "text": "  one\n   two   three ",
            "value": "SECRET",
            "aria_label": None,
            "disabled": False,
        },
        7,
    )
    assert item["text"] == "one two"
    assert "value" not in item
    assert item["aria_label"] is None
    assert item["role"] == "searchb"
