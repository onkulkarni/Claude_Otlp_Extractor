import argparse
import os
import shutil

from extractor import cli

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

JIRA_FIXTURES = [
    "2026-07-10T13-22-44.088Z_logs_000007.json",
    "2026-07-10T13-22-46.801Z_logs_000009.json",
    "2026-07-10T13-22-49.050Z_logs_000011.json",
]


def _make_args(tmp_path, **overrides):
    input_dir = tmp_path / "received"
    logs_dir = input_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    for name in JIRA_FIXTURES:
        shutil.copy(os.path.join(FIXTURES, name), logs_dir / name)

    defaults = dict(
        input=str(input_dir),
        output=str(tmp_path / "extracted"),
        state_dir=str(tmp_path / ".state"),
        csv_path=None,
        jira_map_path=None,
        dry_run=False,
        interval=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_run_once_writes_records_and_jira_map(tmp_path):
    args = _make_args(tmp_path)

    written, skipped = cli.run_once(args)

    assert written == 2
    assert skipped == 0
    assert os.path.exists(os.path.join(args.output, "records.csv"))
    assert os.path.exists(os.path.join(args.output, "session_jira_map.json"))


def test_run_once_is_idempotent_on_repeat_call(tmp_path):
    args = _make_args(tmp_path)

    cli.run_once(args)
    written, skipped = cli.run_once(args)

    assert written == 0
    assert skipped == 2


def test_run_once_dry_run_does_not_write_files(tmp_path):
    args = _make_args(tmp_path, dry_run=True)

    written, skipped = cli.run_once(args)

    assert written == 2
    assert skipped == 0
    assert not os.path.exists(os.path.join(args.output, "records.csv"))


def test_run_interval_calls_run_once_repeatedly_and_stops_on_keyboard_interrupt(tmp_path):
    args = _make_args(tmp_path, interval=0.01)
    sleep_calls = []

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 3:
            raise KeyboardInterrupt

    exit_code = cli.run_interval(args, sleep_fn=fake_sleep)

    assert exit_code == 0
    assert len(sleep_calls) == 3
    assert all(s == 0.01 for s in sleep_calls)
    # first cycle wrote both records; subsequent cycles are idempotent no-ops
    assert os.path.exists(os.path.join(args.output, "records.csv"))
