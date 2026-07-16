# Plan: Enforce Agent/Skills mutual exclusion on output records

## Context

`extractor/correlate.py` tracks `Agent` and `Skills` as two independent per-session,
per-`prompt_id` dicts (`state.agent_by_prompt_id`, `state.skill_by_prompt_id` in
`extractor/state_store.py:11-12`). The `skill_activated` handler
(`extractor/correlate.py:97-104`) routes a *single* event's `skill.name` into one
dict or the other (agent-namespaced `agents:<name>.agent` → `Agent`, everything else
→ `Skills`), and that if/else is mutually exclusive **per event**. But
`_build_record()` (`extractor/correlate.py:46-69`) independently reads both dicts by
`prompt_id` when an `api_request` event fires:

```python
"Agent": state.agent_by_prompt_id.get(prompt_id),
"Skills": state.skill_by_prompt_id.get(prompt_id),
```

Because state persists across incremental CLI runs (`.state/<session_id>.json`) and a
dormant secondary Agent signal also exists (`tool_decision`/`tool_result` →
`agent.extract_agent()`, lines 105-108), a single `prompt_id` can end up with entries
in *both* dicts — e.g. an older run populated `skill_by_prompt_id` before the
agent-routing fix landed (commit `0312f15`), and a later run/signal populated
`agent_by_prompt_id` for the same `prompt_id` without ever clearing the stale Skills
entry. Nothing today enforces "if Agent is set, Skills must be blank" at the point a
record is actually assembled.

This is not hypothetical — it's already on disk. `extracted/records.csv` rows for
session `003ed25f-cd28-4c09-a110-00cc92bcd293` (e.g. request
`req_011Cd3QsUXUU1NPCGywaUiNH`) currently have **both**
`Agent=backend-implementer` and `Skills=agents:backend-implementer.agent` populated.
This is exactly the confusion the user flagged: stats grouped/derived from these
columns (e.g. `consolidate.py`'s `GROUP_KEY_FIELDS = ["Model", "Agent", "Skills",
"JIRA Key"]`) can't cleanly distinguish "agent turn" from "skill turn" while both
columns are non-empty on the same row.

**Goal:** whenever a record's `Agent` is populated, its `Skills` must be blank —
enforced at record-assembly time so it holds regardless of how the upstream state got
polluted — plus a one-time backfill of already-extracted data so existing output
reflects the same invariant.

## Recommended approach

### 1. Enforce the invariant where records are assembled

Change `_build_record()` in `extractor/correlate.py` (lines 46-69) so `Skills` is
forced to `None` whenever `Agent` is truthy:

```python
agent_value = state.agent_by_prompt_id.get(prompt_id)
skill_value = None if agent_value else state.skill_by_prompt_id.get(prompt_id)
...
"Agent": agent_value,
"Skills": skill_value,
```

This is the single authoritative fix point: every output record (per-record JSON via
`writer.write_record()`, `records.csv` via `writer.append_csv_row()`, and everything
downstream that consumes them) goes through `_build_record()`, so this one change
guarantees the invariant for all future extraction runs without needing to touch
`consolidate.py`, `api_payloads.py`, or `writer.py` — they stay agnostic pass-throughs
as they are today.

State-store hygiene (clearing the losing dict entry in `skill_by_prompt_id`/
`agent_by_prompt_id` when the other gets set) is explicitly **out of scope** — the
build-time fix is sufficient since `_build_record()` re-reads state fresh on every
call; stale entries left in `.state/<session_id>.json` are harmless.

### 2. Backfill already-extracted data

Add a new one-off script, `extractor/backfill_skill_when_agent_present.py`, following
the exact read-modify-write pattern already established in
`extractor/backfill_agent_column.py`:

- **`records.csv`**: for any row where `row.get("Agent")` is non-empty and
  `row.get("Skills")` is also non-empty, clear `Skills` to `""`. Same
  read-all/rewrite-temp-file/`os.replace` pattern as
  `backfill_agent_column.py:31-48`, reusing `OUTPUT_FIELDS`/`CSV_FIELDS`.
- **Per-record JSON files** under `extracted/<session_id>/*.json`: glob every
  session directory, load each record, and apply the same rule (clear `"Skills"` to
  `None` when `"Agent"` is truthy), rewriting the file in place. This is a new code
  path (the existing backfill script never touched per-record JSON), but the user
  wants these included so every artifact on disk agrees.
- After both are fixed, regenerate the downstream files exactly as the existing
  backfill script's docstring already instructs: `python -m extractor.consolidate`
  and `python -m extractor.api_payloads` (these rebuild `records_consolidated.csv`
  and `extracted/api_payloads/*.json` purely from the now-corrected `records.csv`, no
  code changes needed there).

### 3. Tests to add

- **`tests/test_correlate.py`**: a new test that seeds a session state (via
  `state_store.save`/`state_store.load`, or directly constructing a `SessionState`)
  with both `agent_by_prompt_id[pid]` and `skill_by_prompt_id[pid]` set for the same
  `prompt_id`, runs an `api_request` event through `process_events()`, and asserts
  the resulting record has `Agent` set and `Skills is None`. This directly covers the
  gap that let the `003ed25f-...` rows through — none of the existing tests
  (`test_agent_prefixed_skill_routes_to_agent_column`,
  `test_non_agent_namespaced_skill_still_routes_to_skills_column`) exercise the case
  where *both* dicts already have entries for the same `prompt_id` before the
  `api_request` fires.
- **New `tests/test_backfill_skill_when_agent_present.py`**: unit test the row-level
  backfill function (rows with both populated → `Skills` cleared; rows with only one
  populated → unchanged) and the per-record JSON backfill function, following the
  structure of how `backfill_agent_column.py` would be tested (no existing test file
  for it today, so this establishes the pattern fresh — small, focused, no fixtures
  needed beyond inline dicts).

## Files to change

1. `extractor/correlate.py` — `_build_record()` (lines 46-69): enforce the
   Agent-implies-no-Skills invariant.
2. `extractor/backfill_skill_when_agent_present.py` — new script: CSV backfill +
   per-record JSON backfill, with a `main()`/argparse entry point mirroring
   `backfill_agent_column.py`.
3. `tests/test_correlate.py` — add the both-dicts-populated regression test.
4. `tests/test_backfill_skill_when_agent_present.py` — new test file for the backfill
   script.
5. Update stale memory `agent_skill_fix_pending.md` / `otlp_agent_skill_mechanism.md`
   once implemented (noted for the next session, not part of the code change itself).

## Verification

1. `python -m pytest tests/ -v` — confirm the new tests pass and no existing test
   (especially `test_agent_prefixed_skill_routes_to_agent_column`,
   `test_run_end_to_end_over_fixture_folder`, and any `consolidate`/`api_payloads`
   tests) regresses.
2. Run the new backfill script against the real `extracted/records.csv` and
   per-record JSON files; re-grep to confirm no row/file has both `Agent` and
   `Skills` non-empty afterward:
   ```
   python -m extractor.backfill_skill_when_agent_present
   ```
3. Regenerate downstream artifacts and spot-check:
   ```
   python -m extractor.consolidate
   python -m extractor.api_payloads
   ```
   Confirm `records_consolidated.csv` and `extracted/api_payloads/*.json` no longer
   show both `agent`/`skills` populated on the same row/payload (e.g. re-check
   session `003ed25f-cd28-4c09-a110-00cc92bcd293`).
4. Process a small fixture set end-to-end (`extractor.correlate.run`) covering a
   session where both an `agents:*.agent` skill and a plain skill fire under the same
   `prompt_id` (may need a new fixture log combining both), and confirm the emitted
   record has `Skills is None`.
