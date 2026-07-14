# Consolidated Session Report — Handoff

> Self-contained handoff for Story A of [APA-43342](https://nice-ce-cxone-prod.atlassian.net/browse/APA-43342) ([APA-43347](https://nice-ce-cxone-prod.atlassian.net/browse/APA-43347)). Read `HANDOFF.md` first for the base extractor design this builds on. Implemented and verified 2026-07-14.

## Goal

Collapse `extracted/records.csv` (one row per `api_request`/LLM call) into one row per **unbroken run** of the same `Model`/`Agent`/`Skills`/`JIRA Key`, per session — so a long session doesn't read as dozens of near-identical rows when what changed was, e.g., only the JIRA key or which skill was active. Read-only report, no changes to `correlate.py`'s record shape or `records.csv` itself.

## Design

**New module**: `extractor/consolidate.py`, following the existing `extractor/session_costs.py` pattern (read-only report over `records.csv`).

- `load_deduped_rows(csv_path)` — reads `records.csv` via `csv.DictReader`, dedupes on `Request ID` (same defensive pattern as `session_costs.load_session_costs`), preserving row order. Missing CSV → `[]`.
- `consolidate_records(csv_path) -> list[dict]`:
  1. Partition deduped rows by `Session ID`, preserving each session's original relative order (a plain dict keyed by session id — insertion order is preserved in Python 3.7+, so first-seen order of sessions is preserved too).
  2. Walk each session's rows in that order; start a new group whenever the tuple `(Model, Agent, Skills, JIRA Key)` differs from the currently-open group. **Recurrence does not re-merge** — the sequence `A, A, B, A` produces 3 groups, not 2.
  3. Per group, emit: `Session ID`, `Session Date` (the **first** row's date — a group can span midnight per `HANDOFF.md`, so this is picked explicitly, not derived from the last row), `Model`/`Agent`/`Skills`/`JIRA Key`/`User Email` (constant within a group by construction), summed `Cost USD`/`Input Tokens`/`Output Tokens`/`Cache Read Tokens`/`Cache Creation Tokens` (each coerced with `float()`/`int()` plus `or 0`, since CSV round-trips everything as strings), and `Request Count` + `Request IDs` (`;`-joined) for traceability back to raw rows.
- CLI: `python -m extractor.consolidate [--csv-path extracted/records.csv] [--output-path extracted/records_consolidated.csv]`. Prints one summary line per group (`Session ID`, `Model`, `JIRA Key`, `Skills`, `Agent`, cost, request count) and writes the full group list to the output CSV using the atomic temp-file + `os.replace` pattern from `extractor/state_store.py` — a full overwrite each run, so there's no "is this group still open" state to reconcile across runs.
- **Not wired into the `--interval` loop** (Story C stays independent) — this remains on-demand/manual, same as `session_costs.py` today.

### Ordering invariant this relies on

Rows for a session are already in `event.sequence` order within `records.csv`, because `correlate.py` sorts `(session_id, event.sequence)` before emission and `writer.py`'s `append_csv_row` only ever appends. **Caveat**: if a session's rows are non-contiguous in the raw CSV (e.g. interleaved with another session's rows from an overlapping/later run), grouping-by-session-first still treats that session's rows as one continuous sequence for run-detection purposes — it does not care about physical interleaving in the file, only about each session's own relative row order. This matches the plan's intent but hasn't been stress-tested against a real multi-run-interleaved CSV; the cross-check test below is the main confidence signal.

## How to run / test manually

**1. Automated tests (fast, no real data needed):**

```
python -m pytest tests/test_consolidate.py -v
```

**2. Manual end-to-end check against the real `received/` sample data.** Use a throwaway `--state-dir` so this doesn't touch your real `.state/`:

PowerShell:
```powershell
python -m extractor --input received --output extracted --state-dir .state_verify
python -m extractor.consolidate --csv-path extracted/records.csv --output-path extracted/records_consolidated.csv
Get-Content extracted/records_consolidated.csv
```

bash:
```bash
python -m extractor --input received --output extracted --state-dir .state_verify
python -m extractor.consolidate --csv-path extracted/records.csv --output-path extracted/records_consolidated.csv
cat extracted/records_consolidated.csv
```

The second command (`extractor.consolidate`) prints one summary line per consolidated group to stdout, and writes the full group list to `records_consolidated.csv`. Sanity checks to eyeball:
- Row count in `records_consolidated.csv` should be noticeably lower than in `records.csv` (e.g. 80 raw rows collapsed to 6 groups against the current `received/` sample data).
- Each group's `Model`/`Agent`/`Skills`/`JIRA Key` should be constant across its `Request Count`; a session that changes JIRA key mid-way should show up as multiple groups, not one.
- `Cost USD`/`Input Tokens`/etc. per group should equal the sum of the underlying rows (spot-check with `grep <session_id> extracted/records.csv` or `Select-String <session_id> extracted/records.csv` against the raw CSV).

Cleanup afterward: delete `.state_verify/`, `extracted/records.csv`, and `extracted/records_consolidated.csv` if this was just a smoke test rather than a real extraction run.

## Verification

- `tests/test_consolidate.py` (7 tests, all passing as of this writing): basic grouping + summation, non-merge on recurrence (`A,A,B,A` → 3 groups), `Session Date` uses first row of group, numeric coercion after CSV round-trip, dedupe by `Request ID`, missing-CSV → `[]`, and a cross-check invariant — summed group costs per session equal `session_costs.load_session_costs()`'s totals for the same fixture CSV.
- Manual dry run against real `received/` sample data (2026-07-14): full extraction run produced 80 records across 2 sessions; `python -m extractor.consolidate` collapsed these into 6 groups (hand-verified against the printed per-group lines — e.g. one session split into 3 groups by model/JIRA-key/skill changes, matching expectation).
- Full suite: `python -m pytest tests/ -v` — 43 passed.

## Explicitly out of scope

- No changes to `correlate.py`'s record shape, `writer.py`'s idempotency, or `records.csv`'s schema.
- No incremental/merge logic — every run fully recomputes and overwrites `records_consolidated.csv` from the current `records.csv`.
- Not integrated into the `--interval` loop (see `HANDOFF_interval_scheduling.md`) — run it manually alongside or after a demo session.
