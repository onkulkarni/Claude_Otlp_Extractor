"""End-to-end regression test for the Agent-implies-no-Skills invariant.

Drives the real pipeline entry points (extractor.cli.run_once ->
extractor.consolidate -> extractor.api_payloads) over a fixture session where
a plain skill and an `agents:*.agent` skill both fire under the same
prompt_id -- the exact shape of the original bug found in
extracted/records.csv for session 003ed25f-cd28-4c09-a110-00cc92bcd293.
"""

import argparse
import csv
import glob
import json
import os
import shutil

from extractor import api_payloads, consolidate

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
E2E_FIXTURE = "2026-07-16T00-00-00.000Z_logs_e2e_both_signals.json"
SESSION_ID = "e2e-both-signals-session"
REQUEST_ID = "req_e2e_both_signals"


def _run_once(input_dir, output_dir, state_dir):
    from extractor.cli import run_once

    args = argparse.Namespace(
        input=str(input_dir),
        output=str(output_dir),
        state_dir=str(state_dir),
        csv_path=None,
        jira_map_path=None,
        dry_run=False,
    )
    return run_once(args)


def test_pipeline_never_emits_both_agent_and_skills_for_same_prompt(tmp_path):
    input_dir = tmp_path / "received"
    logs_dir = input_dir / "logs"
    logs_dir.mkdir(parents=True)
    shutil.copy(os.path.join(FIXTURES, E2E_FIXTURE), logs_dir / E2E_FIXTURE)

    output_dir = tmp_path / "extracted"
    state_dir = tmp_path / ".state"

    written, skipped = _run_once(input_dir, output_dir, state_dir)
    assert written == 1
    assert skipped == 0

    # 1. records.csv: Agent set, Skills blank
    csv_path = output_dir / "records.csv"
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["Agent"] == "backend-implementer"
    assert rows[0]["Skills"] == ""

    # 2. per-record JSON: Agent set, Skills None
    json_files = glob.glob(os.path.join(output_dir, SESSION_ID, "*.json"))
    assert len(json_files) == 1
    with open(json_files[0], encoding="utf-8") as f:
        record = json.load(f)
    assert record["Agent"] == "backend-implementer"
    assert record["Skills"] is None

    # 3. records_consolidated.csv: same invariant holds after consolidation
    consolidated_path = output_dir / "records_consolidated.csv"
    groups = consolidate.consolidate_records(str(csv_path))
    consolidate._write_csv(str(consolidated_path), groups)
    assert len(groups) == 1
    assert groups[0]["Agent"] == "backend-implementer"
    assert groups[0]["Skills"] == ""

    # 4. api_payloads/*.json: same invariant holds in the final API payload shape
    payloads_dir = output_dir / "api_payloads"
    api_payloads.write_payloads(str(consolidated_path), str(payloads_dir))
    payload_files = glob.glob(os.path.join(payloads_dir, "*.json"))
    assert len(payload_files) == 1
    with open(payload_files[0], encoding="utf-8") as f:
        payload = json.load(f)
    assert payload["agent"] == "backend-implementer"
    assert payload["skills"] == ""
