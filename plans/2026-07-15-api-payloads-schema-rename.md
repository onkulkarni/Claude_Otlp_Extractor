# Plan: Rename `extracted/api_payloads/*.json` fields to the updated server contract

> Status: **planned, not yet implemented**. Written 2026-07-15 in a planning-only session (no code changes made). This supersedes the field-mapping section of `plans/2026-07-15-api-payloads.md` (that plan's `api_payloads.py` design/module structure is still accurate — only the JSON key names and a few value shapes have changed). Read both docs before touching code.

## Context

`extractor/api_payloads.py` (implemented per `plans/2026-07-15-api-payloads.md`) already generates one JSON file per row of `records_consolidated.csv` into `extracted/api_payloads/`, using a camelCase schema. The server owner has now supplied an updated sample contract that uses `snake_case` keys and, for a few fields, MongoDB Extended JSON wrapper types instead of plain JSON scalars. This plan documents exactly what must change and flags open questions to confirm before implementing.

## Current vs. target schema

Current output (from `build_payload()` in `extractor/api_payloads.py:28-44`):
```json
{
  "sessionId": "fd6693d5-74b5-4f26-86e2-1086c52c055e",
  "sessionDate": "2026-07-15T00:00:00",
  "model": "claude-sonnet-5",
  "agent": "",
  "emailId": "ashish.sheth@nice.com",
  "skills": [],
  "costUsd": 0.1805964,
  "inputTokens": 2,
  "outputTokens": 673,
  "cacheReadTokens": 35158,
  "cacheCreationTokens": 26658,
  "jiraKey": "CXSUP-258986"
}
```

Target (user-provided sample, 2026-07-15):
```json
{
  "session_id": "sess-seed-00001",
  "session_date": { "$date": "2026-07-03T11:42:32.000Z" },
  "model": "Claude-Sonnet-6",
  "agent": "Front End Developer",
  "email_id": "nikhil.jasrotia@nice.com",
  "skills": "Automation Testing",
  "cost_usd": 195.06,
  "input_tokens": { "$numberLong": "19481" },
  "output_tokens": { "$numberLong": "3205" },
  "cache_read_tokens": { "$numberLong": "4958" },
  "cache_creation_tokens": { "$numberLong": "368" },
  "jira_key": "CXSUP-225716"
}
```

## Field-by-field diff

| Current key | Target key | Value shape change |
|---|---|---|
| `sessionId` | `session_id` | rename only, plain string |
| `sessionDate` | `session_date` | rename **and** wrap: plain ISO string → `{"$date": "<ISO-8601 with milliseconds + Z>"}` (MongoDB Extended JSON date) |
| `model` | `model` | no change |
| `agent` | `agent` | no change |
| `emailId` | `email_id` | rename only |
| `skills` | `skills` | **type change**: JSON array (`[]` / `["docx"]`) → plain string (`"Automation Testing"`) |
| `costUsd` | `cost_usd` | rename only, stays a plain JSON number (not wrapped) |
| `inputTokens` | `input_tokens` | rename **and** wrap: plain int → `{"$numberLong": "<stringified int>"}` (MongoDB Extended JSON long) |
| `outputTokens` | `output_tokens` | same wrap as above |
| `cacheReadTokens` | `cache_read_tokens` | same wrap as above |
| `cacheCreationTokens` | `cache_creation_tokens` | same wrap as above |
| `jiraKey` | `jira_key` | rename only |

Net pattern: every key becomes `snake_case`; the four token-count fields and `session_date` become MongoDB Extended JSON wrapper objects; `skills` collapses from an array to a scalar string; `cost_usd`, `model`, `agent`, `jira_key`, `email_id`, `session_id` are plain-scalar renames only.

## Files that must change

1. **`extractor/api_payloads.py`** — `build_payload()` (lines 28-44) is the only place the schema is defined. Rewrite the returned dict per the diff above.
2. **`extractor_onkar/api_payloads.py`** — confirmed **byte-identical duplicate** of the file above (`diff -rq` shows no differences across the whole `extractor/` vs `extractor_onkar/` packages). Whatever change is made to `extractor/api_payloads.py` must be mirrored here too, unless the duplicate-package question below is resolved first by deleting/consolidating one of them.
3. **`tests/test_api_payloads.py`** — every assertion keyed on the old camelCase names (lines 38-51, 92-93) needs updating to the new keys/shapes, including new assertions for the `$date`/`$numberLong` wrapper structures and the `skills`-as-string change.
4. **`plans/2026-07-15-api-payloads.md`** — its "Target contract" sample (lines 11-26) and field-mapping table (lines 30-44) describe the *old* camelCase contract; update or clearly mark as superseded by this doc so a future reader doesn't implement the stale version.
5. **No changes needed** to `correlate.py`, `consolidate.py`, `writer.py`, `session_costs.py`, `jira_map.py`, or their CSV column names (`Session ID`, `Cost USD`, etc.) — those are internal CSV column names, never emitted as JSON keys, and are out of scope for this rename (confirmed via repo-wide search: the camelCase JSON keys exist *only* in `api_payloads.py`/its test/its plan doc).

## Open questions to confirm before implementing

1. **Are `$date` / `$numberLong` wrappers really wanted, or is this MongoDB Extended JSON meant for a specific ingestion path (e.g. `mongoimport`, or a driver's bulk-insert) rather than a REST API body?** `HANDOFF.md` previously deferred "Phase 2: POST to a server" without a concrete client built yet. Confirm with the server owner whether the *consumer* of these files is a Mongo import step or an HTTP endpoint that itself expects Extended JSON in the request body — this affects whether the wrapping belongs in `api_payloads.py` or in a later sending/transport layer.
2. **`session_date` time-of-day.** The seed sample shows a precise time (`11:42:32`), but the current pipeline (`correlate.py`) only ever captures a date (`YYYY-MM-DD`), never time-of-day — this was already flagged as **open assumption #1** in `plans/2026-07-15-api-payloads.md`. Confirm whether:
   - (a) padding with a fixed time (e.g. `T00:00:00.000Z`) inside the `$date` wrapper is acceptable, or
   - (b) real time-of-day is required, which would need a separate upstream change to retain an actual event timestamp in `correlate.py`/`consolidate.py` (bigger change, out of scope for this rename alone).
3. **`skills` as a single string.** The old plan's assumption #2 wondered whether the server wanted multiple concurrent skills (array); this new sample resolves that — it's a single string. Since the extractor today only ever attributes one skill per session-group anyway (per `HANDOFF.md`), a straight pass-through of the raw value (empty string when absent) should satisfy this with no upstream changes. Confirm empty-skills case: should it be `""` or omitted/`null`?
4. **Duplicate `extractor_onkar/` package.** Confirm whether this is intentional (e.g. a personal working copy) or stale/should be removed/symlinked — otherwise every future change has to be manually duplicated across two identical trees. Not required to resolve before this rename, but flagged since it doubles the edit surface for every file change above.
5. **Existing 22 stale files in `extracted/api_payloads/`.** No manual migration needed — `write_payloads()` already fully clears and regenerates the output directory on every run (`extractor/api_payloads.py:50-52`), so simply re-running `python -m extractor.api_payloads` after the code change replaces them with the new schema.

## Proposed implementation steps for next session

1. Resolve/skip open question #4 (duplicate package) — decide whether to edit both `extractor/` and `extractor_onkar/`, or consolidate first.
2. Update `build_payload()` in `extractor/api_payloads.py` (and its duplicate) per the field-by-field diff table:
   - Rename all keys to `snake_case`.
   - Wrap `session_date` as `{"$date": ...}` using an ISO-8601 string with milliseconds and `Z` suffix (resolve question #2 for what the time component should be).
   - Wrap `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens` as `{"$numberLong": str(value)}` — note the value inside is a **string**, not a bare number.
   - Change `skills` from `[skills] if skills else []` to a plain string pass-through (resolve question #3 for the empty case).
   - Leave `cost_usd`, `model`, `agent`, `jira_key`, `email_id`, `session_id` as plain-scalar renames.
3. Update `tests/test_api_payloads.py` expectations to match, including new tests for the `$date`/`$numberLong` wrapper shapes and the `skills`-as-string behavior (add a dedicated coercion test similar to the existing `costUsd`/`inputTokens` type assertions at lines 52-53).
4. Update `plans/2026-07-15-api-payloads.md`'s target-contract section to point at this doc (or inline the corrected sample), so it doesn't describe a stale schema.
5. Regenerate output: `python -m extractor.api_payloads --csv-path extracted/records_consolidated.csv --output-dir extracted/api_payloads` and manually inspect one file for the new shape.
6. Run `python -m pytest tests/test_api_payloads.py -v`, then the full suite `python -m pytest tests/ -v` to confirm no regressions elsewhere (nothing else should reference the old camelCase keys, per the file-impact list above, but the full suite is cheap insurance).

## Explicitly out of scope for this rename

- Any upstream change to `correlate.py`/`consolidate.py` to capture real `session_date` time-of-day (only needed if question #2 resolves to "yes, real time is required").
- Any change to CSV column names or the CSV-producing modules (`correlate.py`, `writer.py`, `consolidate.py`, `session_costs.py`, `jira_map.py`) — this rename is isolated to the JSON serialization layer in `api_payloads.py`.
- Building the actual HTTP/Mongo-import client that consumes these files — still a separate, not-yet-started piece of work per `HANDOFF.md`'s Phase 2 note.
- Resolving the `extractor_onkar/` duplicate-package situation (flagged as a question, not a decision made here).
