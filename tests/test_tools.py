import importlib

import pytest


class Browser:
    async def wait(self, seconds):
        return {"success": True, "seconds": seconds}


def registry():
    assert importlib.util.find_spec("browser_agent.tools"), "Tools not implemented"
    module = importlib.import_module("browser_agent.tools.registry")
    return module.ToolRegistry(Browser())


@pytest.mark.asyncio
async def test_validation_prevents_invalid_wait():
    tools = registry()
    for args in ({"seconds": 20}, {"seconds": -1}, {"seconds": "1"}, {"seconds": 1, "extra": 4}):
        result = await tools.execute("wait", args)
        assert result["success"] is False
    assert (await tools.execute("wait", {"seconds": 0.2}))["success"] is True


@pytest.mark.asyncio
async def test_unknown_tool_and_url():
    tools = registry()
    assert not (await tools.execute("shell", {}))["success"]
    for url in ("javascript:alert(1)", "file:///etc/passwd", "@url:`https://example.com`"):
        assert not (await tools.execute("navigate_to_url", {"url": url}))["success"]


def test_schemas_match_tools():
    schemas = registry().schemas()
    assert len(schemas) >= 11
    assert all(x["function"]["parameters"]["additionalProperties"] is False for x in schemas)
    assert "get_page_text" not in {x["function"]["name"] for x in schemas}
