# Plan: Route `agents:*.agent` skill activations into the Agent column, not Skills

> Status: **planned, not yet implemented**. Written 2026-07-15 in a planning-only session (no code changes made).

## Context

`extractor/correlate.py` currently has two independent, non-overlapping mechanisms for populating the `Agent` and `Skills` output columns:

- **`Skills`**: on a `skill_activated` event, `correlate.process_events` (`extractor/correlate.py:97-99`) stores `event.get("skill.name")` verbatim into `state.skill_by_prompt_id[prompt_id]`.
- **`Agent`**: on a `tool_decision`/`tool_result` event, `extractor/agent.py:extract_agent()` looks for `tool_name == "Task"` and pulls `subagent_type` out of the tool's JSON input. Its own docstring flags this as **UNVERIFIED** — no sample in `received/` has ever contained a `tool_name == "Task"` event, so this path has never actually fired in production data.

In practice, real session data shows the *Task-based* path is dead and a *different* real mechanism produces subagent info: a `skill_activated` event whose `skill.name` is namespaced `agents:<name>.agent` (e.g. `agents:backend-implementer.agent`, `agents:backend-planner.agent`). Confirmed via `new_received/logs/2026-07-15T06-26-48.227Z_logs_000017.json`:

```json
{
  "event.name": "skill_activated",
  "prompt.id": "e07cef83-74bb-4ca5-bcc2-0f4baabaf87f",
  "skill.name": "agents:backend-implementer.agent",
  "invocation_trigger": "user-slash",
  "skill.source": "userSettings"
}
```

Because this arrives on the same `skill_activated` event type as real skills, today's code dumps it straight into `Skills` and `Agent` stays blank for that request. Confirmed in `extracted/records.csv` — rows for sessions `003ed25f-cd28-4c09-a110-00cc92bcd293` and `3a6a9ae0-867b-4557-b1bf-044bac71b2b3` have `Agent` empty and `Skills` = `agents:backend-implementer.agent` / `agents:backend-planner.agent`.

Full inventory of distinct `skill.name` values seen across `received/`, `new_received/`, `bkp_received/` (via one-off scan of all `skill_activated` events):

| `skill.name` | Namespace meaning | Should become |
|---|---|---|
| `agents:backend-implementer.agent` | subagent launch surfaced as a skill | `Agent = "backend-implementer"` |
| `agents:backend-planner.agent` | subagent launch surfaced as a skill | `Agent = "backend-planner"` |
| `code-explainer:code-explainer` | a real skill | `Skills = "code-explainer:code-explainer"` (unchanged) |
| `instructions:mcp-atlassian-usage.instructions` | a real skill/instruction doc, **not** an agent | `Skills` (unchanged) — out of scope, do not touch |

Only the `agents:` namespace should be redirected. `instructions:` and any other namespace are real skill-like activations and must keep flowing to `Skills`.

## Proposed change

Add a small pure-function parser — e.g. `extractor/agent.py:extract_agent_from_skill_name(skill_name: str) -> str | None` — that returns the agent name when `skill_name` matches the `agents:<name>.agent` pattern (strip the `agents:` prefix and the `.agent` suffix), and `None` otherwise.

In `extractor/correlate.py`'s `skill_activated` branch (currently lines 97-99), check this parser first:

```python
elif event_name == "skill_activated":
    if prompt_id:
        skill_name = event.get("skill.name")
        agent_value = agent.extract_agent_from_skill_name(skill_name)
        if agent_value:
            state.agent_by_prompt_id[prompt_id] = agent_value
        else:
            state.skill_by_prompt_id[prompt_id] = skill_name
```

This keeps the existing (unverified, dead-in-practice) `Task`-based path in `extract_agent()` untouched — it's a separate signal that may someday fire in addition to this one.

## Open questions to confirm before implementing

1. **Exact pattern match.** Is `agents:<name>.agent` the only shape ever produced, or could there be `agents:<name>` without the `.agent` suffix, or nested names with `:` inside `<name>`? Only two concrete samples exist today (`backend-implementer`, `backend-planner`). Recommend matching broadly — prefix `agents:` (required) and stripping a trailing `.agent` suffix only if present — rather than a strict full-pattern regex, so we don't silently drop a slightly-different-shaped value into neither column.
2. **Precedence if both mechanisms fire for the same `prompt_id`.** If the dead `Task`/`subagent_type` path ever *does* start firing (its docstring says it's unverified, not impossible), and a `skill_activated` `agents:*.agent` event also lands on the same `prompt_id`, which should win? Recommend: don't overwrite an already-set `state.agent_by_prompt_id[prompt_id]` — first writer wins — since event order within a prompt is not guaranteed to reflect precedence. Confirm this is acceptable, or whether last-write-wins is preferred instead.
3. **Case sensitivity / whitespace.** Should the prefix match be exact (`"agents:"`) or should it tolerate variants like `"Agents:"`? No evidence of variants in current data; recommend exact match only, revisit if a variant shows up.
4. **Existing bad data already on disk.** `extracted/records.csv`, `extracted/records_consolidated.csv`, and `extracted/api_payloads/*.json` already contain rows with the old (wrong) `agents:*.agent` value sitting in `Skills`. `writer.write_record()` is idempotent per `request_id` (`extractor/writer.py:17-20`, `already_written()` globs the per-record JSON file) — simply re-running `python -m extractor --input ... --output extracted` will **not** regenerate these rows, since the per-record JSON files already exist on disk. Decide between:
   - (a) a one-off backfill script that rewrites existing CSV rows in place (move `Skills` value to `Agent` when it matches the `agents:*.agent` pattern, clear `Skills`), then re-run `extractor/consolidate.py` and `extractor/api_payloads.py` to regenerate the downstream files from the corrected `records.csv`; or
   - (b) delete the affected per-record JSON files (`extracted/003ed25f-.../`, `extracted/3a6a9ae0-.../`, `extracted/73ec5b2d-.../`, and any others found in the inventory grep) plus their `records.csv` rows and `.state/<session_id>.json` entries, then re-run the CLI so it reprocesses those sessions from raw `received/`/`new_received/` data.
   - Recommend (a): it's less destructive and doesn't risk state-store side effects on unrelated fields (e.g. `last_jira_key`) for sessions that have since accumulated more state.

## Files that must change

1. **`extractor/agent.py`** — add `extract_agent_from_skill_name()`; update the module docstring, which currently frames the whole file as being about the unverified `Task`-tool path only.
2. **`extractor/correlate.py`** — update the `skill_activated` branch (lines 97-99) per the proposed change above.
3. **`tests/test_correlate.py`** — add a fixture-driven test alongside the existing `test_skill_scoped_strictly_to_matching_prompt_id`: a `skill_activated` event with `skill.name = "agents:backend-implementer.agent"` should produce a record with `Agent == "backend-implementer"` and `Skills is None`. Also add a negative case confirming `instructions:mcp-atlassian-usage.instructions` (or another non-`agents:` namespace) still lands in `Skills` untouched.
4. **New test file `tests/test_agent.py`** (doesn't exist yet) — direct unit tests for `extract_agent_from_skill_name()`: `"agents:backend-implementer.agent"` → `"backend-implementer"`, `"agents:backend-planner.agent"` → `"backend-planner"`, `"code-explainer:code-explainer"` → `None`, `"instructions:mcp-atlassian-usage.instructions"` → `None`, `None` → `None`.
5. **New test fixture(s)** — copy at least one real `agents:*.agent` `skill_activated` log file into `tests/fixtures/`, e.g. `new_received/logs/2026-07-15T06-26-48.227Z_logs_000017.json` (session `73ec5b2d-56bc-430e-914e-cfde3b69c6f3`, `skill.name: "agents:backend-implementer.agent"`). Follow the existing pattern of listing fixture files with an inline comment explaining what event they carry (see `JIRA_FIXTURES`/`SKILL_FIXTURES` in `tests/test_correlate.py:15-24`).
6. **No changes needed** to `consolidate.py`, `api_payloads.py`, `writer.py`, `session_costs.py`, `jira_map.py` — they all consume `Agent`/`Skills` purely by column name/dict key and are agnostic to how those values were derived. They will pick up the corrected values automatically once `correlate.py` emits them correctly, for any *newly processed* record. (Existing already-written records still need the backfill from open question 4.)

## Proposed implementation steps for next session

1. Resolve open questions 1-4 above (pattern strictness, precedence, case sensitivity, and backfill approach for existing data).
2. Implement `extract_agent_from_skill_name()` in `extractor/agent.py` and wire it into `correlate.py`'s `skill_activated` branch.
3. Add the new fixture file(s) to `tests/fixtures/`, write `tests/test_agent.py`, and extend `tests/test_correlate.py` with the positive (`agents:*.agent` → Agent) and negative (`instructions:*` → Skills, unchanged) cases.
4. Run `python -m pytest tests/ -v` to confirm no regressions, in particular `tests/test_consolidate.py` and `tests/test_api_payloads.py` which read `Agent`/`Skills` off `records.csv`.
5. Execute the chosen backfill approach (recommend option (a) from open question 4) against `extracted/records.csv`, then regenerate `extracted/records_consolidated.csv` (`python -m extractor.consolidate`) and `extracted/api_payloads/*.json` (`python -m extractor.api_payloads`).
6. Spot-check: grep `extracted/records.csv` for `agents:` — after the fix and backfill, it should no longer appear in the `Skills` column, only (as a bare agent name, without the `agents:`/`.agent` wrapper) in the `Agent` column.

## Explicitly out of scope

- Reworking or removing the existing `Task`-tool/`subagent_type` extraction path in `extractor/agent.py` — it stays as a secondary, currently-dormant signal.
- Any change to how `instructions:*` or other non-`agents:` namespaced `skill.name` values are handled — those continue to populate `Skills` unchanged.
- The MongoDB Extended JSON schema rename described in `plans/2026-07-15-api-payloads-schema-rename.md` — unrelated, separate in-flight plan. Note only that its `skills`-as-string and `agent` fields will carry the *corrected* values once both plans are implemented (order between the two doesn't matter functionally, but implementing this one first means the schema-rename work tests against already-correct data).
