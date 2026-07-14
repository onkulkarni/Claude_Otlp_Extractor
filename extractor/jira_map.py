"""Session -> last-known JIRA Key resume map, derived from records.csv.

Backstops correlate.py's per-session .state/<session_id>.json: if that state
is lost/reset, a resumed session can still seed its last_jira_key from this
map instead of starting blank (see HANDOFF_jira_resume_map.md). Stored
deliberately outside .state/ so a .state/ wipe doesn't also destroy this
fallback, and derived from records.csv (the append-only source of truth)
rather than from the state files it's meant to backstop.
"""

import json
import os

from extractor.consolidate import load_deduped_rows


def build_from_csv(csv_path: str) -> dict:
    jira_by_session: dict[str, str] = {}
    for row in load_deduped_rows(csv_path):
        jira_key = row.get("JIRA Key")
        if jira_key:
            jira_by_session[row["Session ID"]] = jira_key  # last-wins in row order
    return jira_by_session


def load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save(path: str, jira_map: dict) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(jira_map, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)
