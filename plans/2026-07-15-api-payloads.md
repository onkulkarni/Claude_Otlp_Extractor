# Plan: Generate per-record JSON API payloads from `records_consolidated.csv`

> Status: **planned, not yet implemented**. Written 2026-07-15 in a planning-only session (no code changes made). Read this file first — it's self-contained — before touching code.

## Context

`HANDOFF.md` explicitly deferred a "Phase 2" to a later session: POSTing one record per LLM call/session-group to a server for analytics storage, once someone obtains the real endpoint URL, request schema, and auth mechanism from the server's owner (this team doesn't own that API). That contract is now available — the user provided a sample `curl` call showing the expected JSON body shape (below). This plan covers **only** the JSON-file-generation step: reading `extracted/records_consolidated.csv` (produced by `extractor/consolidate.py`) and writing one JSON file per row, shaped to match that contract, so a future script can loop over these files and `POST` each one. **Building the actual HTTP client/sender is explicitly out of scope for this plan** — that's the next piece of work after these payload files exist and are reviewed.

## Target contract (from user-provided sample)

```json
{
  "sessionId": "sess-001",
  "sessionDate": "2026-07-09T10:15:00",
  "model": "claude-sonnet-5",
  "agent": "claude-code",
  "emailId": "prashant.deshpande@nice.com",
  "skills": ["docx", "pptx"],
  "costUsd": 0.42,
  "inputTokens": 1200,
  "outputTokens": 800,
  "cacheReadTokens": 300,
  "cacheCreationTokens": 100,
  "jiraKey": "PROJ-123"
}
```

## Field mapping (`records_consolidated.csv` column → JSON key)

| CSV column | JSON key | Notes |
|---|---|---|
| `Session ID` | `sessionId` | direct |
| `Session Date` | `sessionDate` | **See open assumption #1** — source is date-only (`YYYY-MM-DD`); pad to `T00:00:00` to match sample's ISO-datetime shape |
| `Model` | `model` | direct |
| `Agent` | `agent` | pass through as-is (often `null`/empty today — see open assumption #3) |
| `User Email` | `emailId` | direct |
| `Skills` | `skills` | wrap as a list: `[Skills]` if non-empty, else `[]` — **see open assumption #2** |
| `Cost USD` | `costUsd` | coerced to `float` |
| `Input Tokens` | `inputTokens` | coerced to `int` |
| `Output Tokens` | `outputTokens` | coerced to `int` |
| `Cache Read Tokens` | `cacheReadTokens` | coerced to `int` |
| `Cache Creation Tokens` | `cacheCreationTokens` | coerced to `int` |
| `JIRA Key` | `jiraKey` | direct |
| `Request Count`, `Request IDs` | *(dropped from body)* | not present in the sample contract — see open assumption #4. `Request IDs` is still read internally to build the filename (below), just not included in the JSON body sent to the server. |

## Open assumptions — confirm with the server owner before actually sending data

1. **`sessionDate` granularity**: current extraction (`correlate.py`) only ever records the date portion of an event's timestamp, never time-of-day, so there's no real time to put in the `T10:15:00` slot. This plan pads with `T00:00:00`. If the server needs real time-of-day, that requires a separate upstream change to `correlate.py`/`consolidate.py` to retain a timestamp — not part of this plan.
2. **`skills` array**: the sample shows multiple entries (`["docx", "pptx"]`), but the current extractor (per `HANDOFF.md`) only ever attributes a single skill per session-group. This plan emits a 0-or-1-element array. If the server truly expects multiple concurrent skills per session, upstream extraction logic would need to change first.
3. **`agent` field**: sample value `"claude-code"` might be a placeholder, or might indicate the server wants a fixed app/product name rather than our internal subagent type (e.g. `"Explore"`, `"Plan"`) — which itself is flagged `UNVERIFIED` in `HANDOFF.md` (no real sample data has confirmed this extraction yet). This plan passes through whatever is in the `Agent` column unchanged.
4. **Dropped `Request Count`/`Request IDs`**: confirm the server doesn't need per-request traceability back to the raw `records.csv` rows. (The first request ID is still used internally as part of the output filename, so traceability is preserved in the filename even though it's absent from the JSON body.)

## Design

New module `extractor/api_payloads.py`, following the same read-only-report pattern as `extractor/consolidate.py` and `extractor/session_costs.py` (plain functions, argparse CLI, no classes).

- **`load_rows(csv_path) -> list[dict]`**: plain `csv.DictReader` read of `records_consolidated.csv`. No de-dup needed here — `consolidate.py` already dedupes/groups upstream. Missing file → `[]` (same defensive pattern as `consolidate.load_deduped_rows`).
- **`first_request_id(row) -> str`**: `row["Request IDs"].split(";")[0]` — used only for the filename, not the JSON body.
- **`build_payload(row: dict) -> dict`**: pure function implementing the field mapping table above (type coercion + `skills` list-wrapping + `sessionDate` padding). Kept as one small isolated function so it's the single place to edit once the real contract nuances (assumptions #1–#4) are confirmed.
- **`write_payloads(csv_path, output_dir) -> list[str]`**:
  1. `load_rows(csv_path)`.
  2. **Full overwrite**: clear `output_dir` of existing `*.json` files first (matches `consolidate.py`'s own full-overwrite behavior for `records_consolidated.csv` — since the CSV is fully regenerated each run, stale payload files from now-defunct groups shouldn't linger).
  3. For each row: `build_payload(row)`, filename `f"{row['Session ID']}_{first_request_id(row)}.json"`, write under `output_dir` (flat, no session subfolders) via `json.dump(payload, f, indent=2)`.
  4. Return list of written paths.
- **CLI** (`main(argv=None)`): `python -m extractor.api_payloads [--csv-path extracted/records_consolidated.csv] [--output-dir extracted/api_payloads]` — prints one line per written file (`sessionId`, `jiraKey`, `model`, `costUsd`) plus a final count, mirroring `consolidate.py`'s CLI output style. Standard `if __name__ == "__main__": raise SystemExit(main())` footer.

### Files to touch
- **New**: `extractor/api_payloads.py` (module above)
- **New**: `tests/test_api_payloads.py` — mirror `tests/test_consolidate.py`'s structure:
  - `build_payload` field mapping + type coercion (strings → int/float, `sessionDate` padding, `skills` wrapping)
  - empty/missing `Skills` → `skills: []`
  - `first_request_id` splits correctly on `;`
  - `write_payloads` full-overwrite behavior: a stale `.json` file from a prior run (no longer matching any current CSV row) is removed
  - missing CSV path → `load_rows` returns `[]`, `write_payloads` writes nothing (and doesn't crash)
- No changes needed to `extractor/consolidate.py`, `extractor/correlate.py`, or `extractor/writer.py`.

## Explicitly out of scope for this plan

- No HTTP client, no actual `POST` calls, no retry/batching/auth-header logic — that's the next piece of work, built on top of these payload files once reviewed.
- No upstream change to capture real time-of-day for `sessionDate` (assumption #1) or multi-skill tracking (assumption #2) — flagged for confirmation, not implemented here.
- Not wired into the `--interval` loop — run on-demand after `consolidate.py`, same as `consolidate.py` itself is today.

## Verification

1. Ensure `extracted/records_consolidated.csv` exists (regenerate via `python -m extractor.consolidate` if needed, or use one already present in `extracted/`).
2. Run `python -m extractor.api_payloads --csv-path extracted/records_consolidated.csv --output-dir extracted/api_payloads`.
3. Open a generated file under `extracted/api_payloads/` and confirm: camelCase keys match the sample contract exactly, numeric fields are real JSON numbers (not quoted strings), `skills` is a JSON array, `sessionDate` is a full ISO datetime string.
4. Run it a second time back-to-back and confirm the output folder is fully replaced (file count equals current CSV row count, no leftover files from a previous, different CSV).
5. `python -m pytest tests/test_api_payloads.py -v`, then the full suite `python -m pytest tests/ -v` to confirm no regressions.

## Appendix: reference locations found during exploration (2026-07-15)

Captured here so the next session doesn't need to re-explore the codebase from scratch.

- **`records_consolidated.csv` schema** — `CONSOLIDATED_FIELDS` at `extractor/consolidate.py:14-18`: `Session ID, Session Date, Model, Agent, Skills, JIRA Key, User Email, Cost USD, Input Tokens, Output Tokens, Cache Read Tokens, Cache Creation Tokens, Request Count, Request IDs`.
- **Consolidation logic** — `consolidate_records()` at `extractor/consolidate.py:68-93`, grouping/accumulation helpers `_new_group`/`_accumulate` at lines 39-65. CLI entrypoint `main()` at lines 109-133. Full-overwrite CSV write pattern (`.tmp` + `os.replace`) at `_write_csv`, lines 96-106 — this plan's `write_payloads` should follow the same atomic/full-overwrite spirit for the output directory.
- **Existing per-record JSON writer to model the new module loosely on** — `extractor/writer.py`: `write_record()` (lines 40-58) builds `extracted/<session_id>/<ts>_<request_id>.json`, `already_written()` (lines 17-20) does idempotency via glob, `_compact_timestamp()` (lines 13-14). Note: this plan's output is a **flat** directory (`extracted/api_payloads/`), not per-session subfolders, and uses full-overwrite rather than idempotent-skip — a deliberate difference from `writer.py`, decided via user's answers to the planning questions.
- **CLI/module convention to follow** — `extractor/session_costs.py` is the template `consolidate.py`, `jira_map.py` all follow: a read-only report over a CSV, argparse CLI, no wiring into `--interval`. Same pattern applies to `api_payloads.py`.
- **No existing HTTP/API-call code anywhere in the repo** (confirmed via full search — no `requests`, `httpx`, `axios`, `fetch`, sockets, or OTLP exporter code in `extractor/` or `tests/`). `HANDOFF.md:22-24` explicitly states Phase 1 is extraction-only with no HTTP calls. This plan still doesn't introduce any — the actual POST-sending client remains a separate future task.
- **`received/logs/*.json` files are unrelated** — those are raw OTLP Collector dump fixtures (input to `extractor/otlp_flatten.py`/`correlate.py`), not related to this plan's output.
- **Project structure**: pure Python, no Node/JS. Package layout: `extractor/` (otlp_flatten.py, jira.py, agent.py, correlate.py, state_store.py, writer.py, consolidate.py, jira_map.py, session_costs.py, cli.py, `__main__.py`), `tests/` (mirrors modules + `fixtures/`), `received/{logs,metrics,traces}/` (input samples), `extracted/` (gitignored output), `.state/` (gitignored correlation state). No `.env`/config file convention exists — all config is argparse CLI flags (see `extractor/cli.py:59-80`).
- **Related handoff docs for context on the upstream pipeline**: `HANDOFF.md` (base extractor design, Phase 1/2 split, the "Phase 2 note" that motivated this plan), `HANDOFF_consolidation.md` (design + manual test steps for `consolidate.py`, the direct upstream input to this plan).
