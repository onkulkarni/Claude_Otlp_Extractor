# Plan: Consolidation report, JIRA-resume map, interval scheduling, handoff docs

> Status: Approved 2026-07-13, not yet implemented. See [`../HANDOFF.md`](../HANDOFF.md) for the base extractor design this plan builds on.

## Context

`Claude_Otlp_Extractor` is a Phase-1, stdlib-only Python extractor (`extractor/`) that reads Claude Code's OTLP log files from `received/logs/`, correlates events per session, and emits one output record per `api_request` (LLM call) — as a JSON file under `extracted/<session_id>/` and as a row in `extracted/records.csv`. State (`last_jira_key`, per-prompt Skills/Agent) persists per session in `.state/<session_id>.json` so re-runs resume correctly. This design is documented end-to-end in `HANDOFF.md`.

For an upcoming Sparkathon demo, the user wants three additions on top of this pipeline, without disturbing the existing extraction/idempotency contract (per-record JSON files remain the intended Phase 2 hand-off unit):

1. A **consolidated view** of session data that collapses consecutive API-call records into one row per unbroken run of the same Model/JIRA Key/Agent/Skills.
2. Resilience so that if a session is **resumed** after its correlation state was lost/reset, its JIRA Key is still correctly attributed going forward.
3. The ability to **run the extractor unattended every 5 minutes** for the live demo.
4. **Three separate handoff documents** (one per story), written at the end of the implementation session, in the same self-contained style as `HANDOFF.md`.

All three confirmed as additive/derived changes — no modification to `correlate.py`'s core record shape, `writer.py`'s idempotency (`already_written`), or the existing `records.csv`/per-record JSON schema.

## Story A — Consolidated session report

**New module `extractor/consolidate.py`**, following the existing `extractor/session_costs.py` pattern (read-only report over `records.csv`, no changes to raw data):

- `load_deduped_rows(csv_path)` — read `records.csv`, dedupe by `Request ID` (same defensive pattern as `session_costs.load_session_costs`), preserving row order.
- `consolidate_records(csv_path) -> list[dict]`:
  - Group deduped rows by `Session ID`, preserving encounter order (rows for a session are already in `event.sequence` order because `correlate.py` sorts `(session_id, event.sequence)` before emission and `writer.py` only ever appends — this ordering invariant should get a one-line comment and a test).
  - Walk each session's rows in order; start a new group whenever the tuple `(Model, Agent, Skills, JIRA Key)` differs from the currently-open group (explicit: `A, A, B, A` → 3 groups, not 2 — recurrence does not re-merge).
  - Aggregate per group: `Session ID`, `Session Date` (first row's date — a group can span midnight per HANDOFF.md, so pick group-start explicitly), `Model`/`Agent`/`Skills`/`JIRA Key`/`User Email` (constant within group), sum `Cost USD`/`Input Tokens`/`Output Tokens`/`Cache Read Tokens`/`Cache Creation Tokens` (coerce with `float()`/`int()` and an `or 0` fallback since CSV round-trips everything as strings), plus `Request Count` and `Request IDs` (joined) for traceability back to raw rows.
- CLI `main()` (same shape as `session_costs.main`): `python -m extractor.consolidate [--csv-path extracted/records.csv] [--output-path extracted/records_consolidated.csv]`. Prints one summary line per group and writes the full group list to `records_consolidated.csv`, using the atomic temp-file + `os.replace` pattern from `extractor/state_store.py` (full overwrite each run — no incremental merge, so there's no "is this group still open" state to reconcile, and it stays correct no matter how many times it's re-run).
- **Not wired into the `--interval` loop** (Story C) — stays on-demand/manual, same as `session_costs.py` today.

**Tests** (`tests/test_consolidate.py`): basic grouping + summation; non-merge on recurrence (`A,A,B,A`); `Session Date` uses first row; numeric coercion after CSV round-trip; dedupe by `Request ID`; a cross-check invariant that summed group costs per session equal `session_costs.load_session_costs()`'s totals for the same fixture CSV.

## Story B — Session→JIRA resume map

**New module `extractor/jira_map.py`**:

- `build_from_csv(csv_path) -> dict[session_id, jira_key]` — reuse the same dedupe-by-`Request ID` + row-order walk as Story A; for each row with a non-empty `JIRA Key`, set `map[session_id] = jira_key` (last-wins in row order, mirroring the live carry-forward semantics). Missing/empty CSV → `{}`.
- `save(path, map)` / `load(path)` — atomic write, same pattern as `state_store.py`. Default path: `extracted/session_jira_map.json` (deliberately **outside** `.state/`, so a `.state/` wipe — the actual failure mode being protected against — doesn't also destroy the fallback; and derived from `records.csv`, the append-only source of truth, rather than from the state files it's meant to backstop).

**Wiring**:
- `extractor/correlate.py`: `process_events(events, state_dir, jira_fallback: dict | None = None)` — when a session's state is first loaded in a run and `state.last_jira_key is None`, seed it from `jira_fallback.get(session_id)` before processing that session's events. Pure-function change, no I/O added to `correlate.py` itself.
- `extractor/cli.py`: before calling `correlate.run(...)`, build `jira_fallback = jira_map.build_from_csv(csv_path)` (guard for first-ever run with no CSV yet). After writing this run's new records (which appends to the CSV), rebuild from the now-updated CSV and `jira_map.save(...)` to the default path — keeps the snapshot file current for the next run/inspection. Add `--jira-map-path` flag mirroring the existing `--csv-path` flag's default-derivation-from-`--output` pattern.

**Tests**: `tests/test_jira_map.py` (build-from-csv basic + last-non-null-wins + missing-file handling; atomic save/load roundtrip). Extend `tests/test_correlate.py`: a session with no `user_prompt` event in this run's events, given `jira_fallback={session_id: "APA-1"}`, produces `api_request` records with `JIRA Key = "APA-1"` from the very first record — simulating a resumed session after state loss.

## Story C — Interval scheduling

**Extend `extractor/cli.py`**:
- Add `--interval SECONDS` (optional; omitted = current one-shot behavior, unchanged).
- Refactor the existing single-pass body (correlate → write/dry-run → print summary) into a small `run_once(args) -> (written, skipped)` helper, so it's unit-testable without sleeping.
- When `--interval` is set: loop `run_once`, print a timestamped per-cycle summary line, then sleep via an injectable `_sleep` parameter (defaults to `time.sleep`, overridable in tests to avoid real waits and to bound iteration count in a test). Catch `KeyboardInterrupt` for a clean exit (exit code 0, final summary line).
- Demo invocation: `python -m extractor --input received --output extracted --interval 300`.

**Tests**: `tests/test_cli.py` (new file) — `run_once` behaves identically to today's one-shot run; interval loop calls `run_once` repeatedly via the injected fake sleep and stops cleanly on a simulated `KeyboardInterrupt`.

## Story D — Handoff documents

Once A–C are implemented and verified (end of the implementation session), write three self-contained handoff docs at repo root, matching `HANDOFF.md`'s structure (Goal, Design, Verification checklist, Explicitly out of scope, any Unverified/flagged items):
- `HANDOFF_consolidation.md`
- `HANDOFF_jira_resume_map.md`
- `HANDOFF_interval_scheduling.md`

Each should stand alone (a fresh session with no prior context could pick up from it), reference the exact files/functions touched, and call out anything not yet validated (e.g., Story A/B's ordering-invariant assumption about `records.csv`, Story C's unbounded per-tick file-rescan cost over a long-running demo).

## Verification

- `python -m pytest tests/ -v` — full suite green, including the 3 new/extended test files above.
- Manual dry run against the existing `received/` sample data: run extraction once, then `python -m extractor.consolidate` and confirm grouped totals match hand-inspection of `records.csv`; delete/rename `.state/` and re-run to confirm `extracted/session_jira_map.json` correctly seeds the JIRA key for the affected session's next records; run `python -m extractor --input received --output extracted --interval 10` briefly and Ctrl+C to confirm clean looped-and-stopped behavior.
