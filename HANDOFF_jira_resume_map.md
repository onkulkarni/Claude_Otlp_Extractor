# Session→JIRA Resume Map — Handoff

> Self-contained handoff for Story B of [APA-43342](https://nice-ce-cxone-prod.atlassian.net/browse/APA-43342) ([APA-43343](https://nice-ce-cxone-prod.atlassian.net/browse/APA-43343)). Read `HANDOFF.md` first for the base extractor design this builds on. Implemented and verified 2026-07-14.

## Goal

Make JIRA-key attribution resilient to `.state/` being lost or reset. Today, `correlate.py`'s per-session `last_jira_key` lives only in `.state/<session_id>.json` (see `HANDOFF.md`). If that file is deleted/reset mid-demo and the session is later "resumed" (new OTLP files for that same `session.id` arrive, but without a fresh JIRA-mentioning `user_prompt` in them — e.g. because the user hasn't retyped the ticket key in a while), the extractor would silently start emitting records with `JIRA Key = None` instead of correctly carrying the key forward. This story adds a fallback so that doesn't happen.

## Design

**New module**: `extractor/jira_map.py`

- `build_from_csv(csv_path) -> dict[session_id, jira_key]` — reuses `extractor.consolidate.load_deduped_rows` (same dedupe-by-`Request ID` + row-order walk as Story A). For each row with a non-empty `JIRA Key`, sets `map[session_id] = jira_key` — **last-wins in row order**, mirroring the live carry-forward semantics in `correlate.py`. Missing/empty CSV → `{}`.
- `save(path, jira_map)` / `load(path)` — atomic write (temp file + `os.replace`), same pattern as `extractor/state_store.py`. Default path: `extracted/session_jira_map.json` — **deliberately outside `.state/`**, so the exact failure mode this backstops (a `.state/` wipe) can't also destroy the fallback. Also deliberately derived from `records.csv` (the append-only source of truth for what was actually emitted) rather than from the state files it exists to protect against.

**Wiring**:
- `extractor/correlate.py`: `process_events(events, state_dir, jira_fallback=None)` (also threaded through `run(input_dir, state_dir, jira_fallback=None)`) — when a session's state is first loaded during a run, if `state.last_jira_key is None`, it's seeded from `jira_fallback.get(session_id)` before any events for that session are processed. Pure-function change; no I/O added inside `correlate.py` itself — `jira_fallback` is just a plain dict passed in.
- `extractor/cli.py`: `run_once(args)` now (a) builds `jira_fallback = jira_map.build_from_csv(csv_path)` before calling `correlate.run(...)`, and (b) after writing the run's new records (which appends to `records.csv`), rebuilds from the now-updated CSV and calls `jira_map.save(...)` — keeping the snapshot current for the next run. New `--jira-map-path` flag mirrors the existing `--csv-path` flag's default-derivation-from-`--output` pattern (`<output>/session_jira_map.json` if unset). The map is **not** rebuilt/saved on `--dry-run` (no files are written in that mode, so there's nothing new to snapshot).

## How to run / test manually

**1. Automated tests (fast, no real data needed):**

```
python -m pytest tests/test_jira_map.py tests/test_correlate.py -v
```

**2. Manual end-to-end check that the map is built and stays current.** Use a throwaway `--state-dir`/`--output` so this doesn't touch real state:

PowerShell:
```powershell
python -m extractor --input received --output extracted --state-dir .state_verify
Get-Content extracted/session_jira_map.json
```

bash:
```bash
python -m extractor --input received --output extracted --state-dir .state_verify
cat extracted/session_jira_map.json
```

You should see one `session_id: "JIRA-KEY"` entry per session, matching that session's last-known JIRA key in `extracted/records.csv`.

**3. Manual check of the actual resilience scenario (state loss + resume):**

PowerShell:
```powershell
Remove-Item -Recurse -Force .state_verify
python -m extractor --input received --output extracted --state-dir .state_verify
python -m extractor.session_costs --csv-path extracted/records.csv   # sanity: totals unchanged
```

bash:
```bash
rm -rf .state_verify
python -m extractor --input received --output extracted --state-dir .state_verify
python -m extractor.session_costs --csv-path extracted/records.csv   # sanity: totals unchanged
```

Because the full `received/` sample still contains each session's original JIRA-bearing `user_prompt` event, this re-run is expected to be a no-op (`Wrote 0 record(s), skipped N already-written`) — it self-heals with or without the fallback. **To actually see the fallback do work**, you'd need a fresh subset of input files for a session that omits its original JIRA-mentioning prompt (e.g. copy only `tests/fixtures/2026-07-10T13-26-00.510Z_logs_000146.json` and `..._000148.json` into a scratch `received/logs/` folder, with no other files for that session) and pass a pre-seeded `--jira-map-path` pointing at a JSON file containing `{"<that session's id>": "APA-1"}` — the emitted record's `JIRA Key` should be `"APA-1"`. This exact scenario is what `tests/test_correlate.py::test_jira_fallback_seeds_session_with_lost_state` already automates, so it's usually easier to just read/re-run that test than to reconstruct it by hand.

Cleanup afterward: delete `.state_verify/`, `extracted/records.csv`, `extracted/session_jira_map.json` if this was just a smoke test.

## Verification

- `tests/test_jira_map.py` (5 tests): build-from-CSV basic case, last-non-null-wins across multiple rows for the same session, missing-CSV → `{}`, atomic save/load round-trip, load of a missing path → `{}`.
- `tests/test_correlate.py` extended with 2 new cases:
  - `test_jira_fallback_seeds_session_with_lost_state` — a session whose only fixture events in this run (`skill_activated` + `api_request`) carry no JIRA-key-bearing `user_prompt`, given `jira_fallback={session_id: "APA-1"}`, produces its `api_request` record with `JIRA Key = "APA-1"` — simulating a resumed session after state loss.
  - `test_jira_fallback_does_not_override_state_that_still_has_a_key` — when the run's own events do contain a JIRA-bearing `user_prompt`, that wins over the fallback (fallback only fills a gap, never overrides live data).
- Manual check against real `received/` sample data (2026-07-14): ran full extraction once (80 records, 2 sessions); confirmed `extracted/session_jira_map.json` was written with the correct last-known key per session (`APA-43308`, `APA-43311`); deleted `.state/` and re-ran over the same full input — output was unchanged (0 new records, 80 skipped as already-written), which is expected since the full input still contains the original JIRA-bearing `user_prompt` events and self-heals regardless of the fallback. The fallback's actual value only shows up when a resumed session's *new* input files don't include that original prompt — exactly what the two new `test_correlate.py` cases exercise directly.
- Full suite: `python -m pytest tests/ -v` — 43 passed.

## Explicitly out of scope / caveats

- No changes to `correlate.py`'s core record shape, `writer.py`'s idempotency, or `records.csv`'s schema.
- The fallback only ever fills in `last_jira_key` when a session's loaded state has none (`None`) — it does not affect `skill_by_prompt_id`/`agent_by_prompt_id`, since those are strictly per-turn and don't have carry-forward semantics that would benefit from a similar backstop.
- The manual verification above could only exercise the "no functional change to a healthy input set" path, not a true resumed-after-loss scenario with genuinely new input files lacking the original prompt — that scenario is covered by the two new unit tests in `test_correlate.py` instead, using fixture data crafted to match that exact shape.
