from extractor.agent import extract_agent_from_skill_name


def test_agent_skill_name_strips_prefix_and_suffix():
    assert extract_agent_from_skill_name("agents:backend-implementer.agent") == "backend-implementer"
    assert extract_agent_from_skill_name("agents:backend-planner.agent") == "backend-planner"


def test_non_agent_namespaces_return_none():
    assert extract_agent_from_skill_name("code-explainer:code-explainer") is None
    assert extract_agent_from_skill_name("instructions:mcp-atlassian-usage.instructions") is None


def test_none_input_returns_none():
    assert extract_agent_from_skill_name(None) is None
