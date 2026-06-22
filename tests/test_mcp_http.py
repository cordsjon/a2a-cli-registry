from core.mcp.http import build_mcp_app
from core.mcp.server import build_mcp_tools


def test_mcp_http_app_is_asgi_and_exposes_registry_tools():
    # build_mcp_app returns a mounted ASGI app; its tool set == the shared registry
    app = build_mcp_app(session=None)   # tool LIST does not need a live session
    assert app is not None
    assert callable(app)                # ASGI app is callable
    # parity: the tool names the HTTP surface advertises == build_mcp_tools()
    from core.mcp.http import mcp_tool_names
    assert set(mcp_tool_names()) == {t["name"] for t in build_mcp_tools()}
