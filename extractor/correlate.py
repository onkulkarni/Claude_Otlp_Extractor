"""Stateful single pass over flattened OTLP log events -> output records."""

import glob
import json
import os

from extractor import agent, jira, otlp_flatten, state_store

OUTPUT_FIELDS = [
    "Session ID",
    "Session Date",
    "Model",
    "Agent",
    "Skills",
    "Cost USD",
    "Input Tokens",
    "Output Tokens",
    "Cache Read Tokens",
    "Cache Creation Tokens",
    "JIRA Key",
    "User Email",
]


def _sort_key(event: dict):
    session_id = event.get("session.id")
    seq = event.get("event.sequence")
    ts = event.get("event.timestamp") or ""
    # event.sequence is monotonic only within a session; never compare across sessions.
    return (session_id, seq if seq is not None else float("inf"), ts)


def load_and_sort_events(input_dir: str) -> list:
    logs_dir = os.path.join(input_dir, "logs")
    files = sorted(glob.glob(os.path.join(logs_dir, "*.json")))
    events = []
    for path in files:
        source_file = os.path.join("logs", os.path.basename(path)).replace(os.sep, "/")
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        events.extend(otlp_flatten.iter_log_records(doc, source_file))
    events.sort(key=_sort_key)
    return events


def _build_record(event: dict, state: state_store.SessionState) -> dict:
    prompt_id = event.get("prompt.id")
    timestamp = event.get("event.timestamp") or ""
    return {
        "Session ID": event.get("session.id"),
        "Session Date": timestamp[:10] or None,
        "Model": event.get("model"),
        "Agent": state.agent_by_prompt_id.get(prompt_id),
        "Skills": state.skill_by_prompt_id.get(prompt_id),
        "Cost USD": event.get("cost_usd"),
        "Input Tokens": event.get("input_tokens"),
        "Output Tokens": event.get("output_tokens"),
        "Cache Read Tokens": event.get("cache_read_tokens"),
        "Cache Creation Tokens": event.get("cache_creation_tokens"),
        "JIRA Key": state.last_jira_key,
        "User Email": event.get("user.email"),
        "_meta": {
            "request_id": event.get("request_id"),
            "prompt_id": prompt_id,
            "query_source": event.get("query_source"),
            "source_file": event.get("_source_file"),
            "event_timestamp": event.get("event.timestamp"),
        },
    }


def process_events(events: list, state_dir: str, jira_fallback: dict | None = None) -> list:
    states: dict[str, state_store.SessionState] = {}
    records = []
    jira_fallback = jira_fallback or {}

    for event in events:
        session_id = event.get("session.id")
        if session_id is None:
            continue
        if session_id not in states:
            state = state_store.load(state_dir, session_id)
            if state.last_jira_key is None:
                fallback_key = jira_fallback.get(session_id)
                if fallback_key:
                    state.last_jira_key = fallback_key
            states[session_id] = state
        state = states[session_id]

        event_name = event.get("event.name")
        prompt_id = event.get("prompt.id")

        if event_name == "user_prompt":
            found_key = jira.extract_jira_key(event.get("prompt"))
            if found_key:
                state.last_jira_key = found_key
        elif event_name == "skill_activated":
            if prompt_id:
                state.skill_by_prompt_id[prompt_id] = event.get("skill.name")
        elif event_name in ("tool_decision", "tool_result"):
            agent_value = agent.extract_agent(event)
            if agent_value and prompt_id:
                state.agent_by_prompt_id[prompt_id] = agent_value
        elif event_name == "api_request":
            records.append(_build_record(event, state))
        # everything else (hook_execution_*, assistant_response, plugin_loaded,
        # hook_registered, mcp_server_connection, non-Task tool_decision/tool_result)
        # is ignored for Phase 1.

    for session_id, state in states.items():
        state_store.save(state_dir, session_id, state)

    return records


def run(input_dir: str, state_dir: str, jira_fallback: dict | None = None) -> list:
    events = load_and_sort_events(input_dir)
    return process_events(events, state_dir, jira_fallback=jira_fallback)
