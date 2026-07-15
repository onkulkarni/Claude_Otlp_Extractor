"""Agent extraction.

Two independent signals populate the Agent column:

- `extract_agent_from_skill_name`: the confirmed, production-verified path. A
  subagent launch surfaces as a `skill_activated` event whose `skill.name` is
  namespaced `agents:<name>.agent` (e.g. `agents:backend-implementer.agent`).
- `extract_agent`: from `tool_name == "Task"` tool calls. UNVERIFIED -- no
  sample in received/ contains such an event. Inferred from Claude Code's
  known tool schema. Kept as a secondary, currently-dormant signal.
"""

import json

TASK_TOOL_NAME = "Task"  # <-- adjust here once verified

AGENT_SKILL_PREFIX = "agents:"
AGENT_SKILL_SUFFIX = ".agent"


def extract_agent_from_skill_name(skill_name: str | None) -> str | None:
    if not skill_name or not skill_name.startswith(AGENT_SKILL_PREFIX):
        return None
    name = skill_name[len(AGENT_SKILL_PREFIX):]
    if name.endswith(AGENT_SKILL_SUFFIX):
        name = name[: -len(AGENT_SKILL_SUFFIX)]
    return name or None


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
