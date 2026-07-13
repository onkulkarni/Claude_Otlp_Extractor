"""Per-session correlation state, persisted as .state/<session_id>.json."""

import json
import os
from dataclasses import asdict, dataclass, field


@dataclass
class SessionState:
    last_jira_key: str | None = None
    skill_by_prompt_id: dict = field(default_factory=dict)
    agent_by_prompt_id: dict = field(default_factory=dict)


def _path(state_dir: str, session_id: str) -> str:
    return os.path.join(state_dir, f"{session_id}.json")


def load(state_dir: str, session_id: str) -> SessionState:
    path = _path(state_dir, session_id)
    if not os.path.exists(path):
        return SessionState()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return SessionState(
        last_jira_key=data.get("last_jira_key"),
        skill_by_prompt_id=data.get("skill_by_prompt_id", {}),
        agent_by_prompt_id=data.get("agent_by_prompt_id", {}),
    )


def save(state_dir: str, session_id: str, state: SessionState) -> None:
    os.makedirs(state_dir, exist_ok=True)
    path = _path(state_dir, session_id)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(asdict(state), f, indent=2)
    os.replace(tmp_path, path)
