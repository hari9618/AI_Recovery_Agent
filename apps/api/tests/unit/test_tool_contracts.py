"""Contract invariants over the whole tool catalog (they fail when someone adds a tool carelessly)."""

import pytest

from app.mcp.server import build_server
from app.tools import REGISTRY

TOOLS = REGISTRY.all()
REQUIRED_MCP = {
    "revenue.get_at_risk_opportunities", "revenue.get_customer_intelligence", "revenue.search_knowledge",
    "revenue.calculate_risk", "revenue.create_followup", "revenue.request_approval", "revenue.get_recovery_report",
}


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t.name)
def test_every_tool_is_fully_described(tool):
    assert tool.description and len(tool.description) > 15
    assert tool.title and tool.input_model and tool.output_model
    assert tool.name.isidentifier()


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t.name)
def test_annotations_are_derived_from_effects(tool):
    a = tool.effects.annotations()
    assert a["readOnlyHint"] == tool.effects.read_only
    assert a["destructiveHint"] == (tool.effects.customer_facing or tool.effects.financial)


def test_llm_can_only_call_read_only_tools():
    exposed = REGISTRY.llm_tools()
    assert exposed, "copilot needs tools"
    for t in exposed:
        assert t.effects.read_only and not t.effects.calls_llm, t.name


def test_customer_facing_and_financial_tools_require_an_approval_id():
    gated = [t for t in TOOLS if t.effects.customer_facing or t.effects.financial]
    assert {t.name for t in gated} == {"send_email", "offer_discount"}
    for t in gated:
        assert "approval_request_id" in t.input_model.model_fields
        assert not t.llm_exposed and t.mcp_name is None


def test_tools_returning_external_text_are_marked_untrusted():
    for name in ("get_conversation", "search_knowledge_base", "analyze_conversation", "get_customer_intelligence"):
        assert REGISTRY.get(name).untrusted_content, name


def test_mcp_surface_matches_spec():
    assert {t.mcp_name for t in REGISTRY.mcp_tools()} == REQUIRED_MCP
    assert all(t.mcp_name.startswith("revenue.") for t in REGISTRY.mcp_tools())


async def test_mcp_schemas_mirror_pydantic_contracts():
    server = build_server()
    listed = {t.name: t for t in await server.list_tools()}
    assert set(listed) == REQUIRED_MCP
    for tool in REGISTRY.mcp_tools():
        schema = listed[tool.mcp_name].input_schema
        required = {n for n, f in tool.input_model.model_fields.items() if f.is_required()}
        assert set(schema.get("required") or []) == required, tool.name
        assert set(schema.get("properties", {})) == set(tool.input_model.model_fields), tool.name
        assert listed[tool.mcp_name].annotations.read_only_hint == tool.effects.read_only
