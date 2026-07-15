"""JIRA key extraction from free-text prompts."""

import re

JIRA_KEY_RE = re.compile(r"[A-Z][A-Z0-9]+-\d+")


def extract_jira_key(text: str) -> str | None:
    if not text:
        return None
    match = JIRA_KEY_RE.search(text)
    return match.group(0) if match else None
