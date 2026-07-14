# Interval Scheduling — Handoff

> Self-contained handoff for Story C of [APA-43342](https://nice-ce-cxone-prod.atlassian.net/browse/APA-43342) ([APA-43345](https://nice-ce-cxone-prod.atlassian.net/browse/APA-43345)). Read `HANDOFF.md` first for the base extractor design this builds on. Implemented and verified 2026-07-14.

## Goal

Let `extractor/cli.py` run unattended on a fixed cadence (e.g. every 5 minutes) for a live Sparkathon demo, instead of requiring a manual re-invocation each time new OTLP files land in `received/logs/`. Omitting the new flag leaves today's one-shot behavior completely unchanged.

## Design

**Extended `extractor/cli.py`**:

- Existing single-pass body (build JIRA fallback → `correlate.run` → write/dry-run → print summary → save JIRA map) was extracted into `run_once(args) -> (written, skipped)`, so it's unit-testable without sleeping and independent of the interval loop. This refactor also carries Story B's JIRA-fallback wiring (see `HANDOFF_jira_resume_map.md`) — the two stories share this function.
- New `--interval SECONDS` flag (`type=float`, default `None`). When unset, `main()` calls `run_once(args)` once and returns — identical to pre-Story-C behavior.
- When set, `main()` calls `run_interval(args, sleep_fn=time.sleep)`, which loops: call `run_once`, print a timestamped per-cycle summary line (`[<UTC ISO timestamp>] cycle N: wrote X, skipped Y`), then sleep for `args.interval` seconds via the injectable `sleep_fn` parameter (defaults to `time.sleep`, overridable in tests to avoid real waits and to bound iteration count). `KeyboardInterrupt` (Ctrl+C) is caught for a clean exit — prints a final "stopped after N cycle(s)" line and returns exit code `0`.
- Demo invocation: `python -m extractor --input received --output extracted --interval 300`.

Each tick is a **full re-scan** of `received/logs/` plus a full re-parse of every JSON file in it (see `correlate.load_and_sort_events` — unchanged by this story) — idempotency (via `writer.already_written`) is what keeps repeated ticks cheap on the *output* side, but the *input*-side cost grows with the total number of files ever dropped into `received/logs/`, not just new ones since the last tick. Fine for a short demo; would need an incremental/watermarked file scan for a long-running deployment.

## How to run / test manually

**1. Automated tests (fast, no real data needed, no actual sleeping):**

```
python -m pytest tests/test_cli.py -v
```

**2. Confirm one-shot behavior is unchanged (no `--interval`):**

```
python -m extractor --input received --output extracted --state-dir .state_verify
```
Should print `Wrote N record(s), skipped 0 already-written (idempotent).` and return immediately, same as before this story.

**3. Manual check of the actual interval loop.** Use a short interval and a small `--output`/`--state-dir` so cycles are cheap, and stop it yourself with **Ctrl+C** in an interactive terminal (a real terminal Ctrl+C sends `SIGINT` your OS delivers to the Python process directly — piping/backgrounding the process, or sending signals via a job-control wrapper, can behave differently and isn't a reliable way to test this):

PowerShell:
```powershell
python -m extractor --input received --output extracted --state-dir .state_verify --interval 10
```

bash:
```bash
python -m extractor --input received --output extracted --state-dir .state_verify --interval 10
```

Let it print at least 2-3 `[<timestamp>] cycle N: wrote X, skipped Y` lines (first cycle writes real records, later cycles should show `wrote 0` since re-scanning the same `received/` folder is idempotent), then press **Ctrl+C**. Expect a final `Interval loop stopped after N cycle(s).` line and a clean process exit (exit code `0` — check with `echo $LASTEXITCODE` in PowerShell or `echo $?` in bash immediately after).

Cleanup afterward: delete `.state_verify/` and `extracted/` if this was just a smoke test.

## Verification

- `tests/test_cli.py` (4 new tests):
  - `test_run_once_writes_records_and_jira_map` / `test_run_once_is_idempotent_on_repeat_call` / `test_run_once_dry_run_does_not_write_files` — confirm `run_once` behaves identically to the pre-refactor one-shot `main()` body (writes records + JIRA map on first call, is a no-op idempotent skip on a repeat call, and writes nothing in `--dry-run`).
  - `test_run_interval_calls_run_once_repeatedly_and_stops_on_keyboard_interrupt` — injects a fake `sleep_fn` that raises `KeyboardInterrupt` on its 3rd call; asserts `run_interval` returns exit code `0`, called sleep exactly 3 times with the configured interval, and that records were written on the first cycle.
- Full suite: `python -m pytest tests/ -v` — 43 passed (includes all of Story A/B's tests too, since this session implemented all three together).
- **Manual verification caveat**: attempted a live `--interval` run with a real Ctrl+C-equivalent (sending `SIGINT` via `timeout -s INT` in the Windows/Git-Bash sandbox used for this session) to visually confirm the loop-and-clean-stop behavior end-to-end. The signal did not propagate to the Python process as a `KeyboardInterrupt` in that environment (a Windows console-signal-delivery quirk, not specific to this code) — the process had to be force-stopped instead. The automated test above exercises the identical in-process code path (`run_interval` catching `KeyboardInterrupt` around the sleep call) and is the reliable verification for this behavior; a real terminal Ctrl+C (as opposed to a piped/backgrounded `SIGINT`) should behave normally, but this was not re-confirmed interactively before writing this handoff.

## Explicitly out of scope

- No changes to `correlate.py`'s record shape, `writer.py`'s idempotency, or `records.csv`'s schema.
- No incremental file-scan optimization — see the per-tick cost caveat above; out of scope for the Sparkathon demo's timeframe.
- `extractor/consolidate.py` (Story A) is intentionally **not** wired into this loop — it remains a manual/on-demand report, run separately during or after the demo.
