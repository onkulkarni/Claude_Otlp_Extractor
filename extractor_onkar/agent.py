"""Agent extraction from subagent-launching tool calls.

UNVERIFIED: no sample in received/ contains a tool_name == "Task" event.
Inferred from Claude Code's known tool schema. MUST be validated against a
real subagent-invoking session before being trusted in production.
"""

import json

TASK_TOOL_NAME = "Task"  # <-- adjust here once verified


def extract_agent(event: dict) -> str | None:
    if event.get("tool_name") != TASK_TOOL_NAME:
        return None
    raw = event.get("tool_input")
    if not raw:
        return None
    try:
        return json.loads(raw).get("subagent_type")
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None
