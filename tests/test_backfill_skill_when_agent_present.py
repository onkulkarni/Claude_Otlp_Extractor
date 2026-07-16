import csv
import json
import os

from extractor import backfill_skill_when_agent_present as backfill
from extractor.correlate import OUTPUT_FIELDS

CSV_FIELDS = OUTPUT_FIELDS + ["Request ID"]


def _row(agent="", skills=""):
    row = {field: "" for field in CSV_FIELDS}
    row["Agent"] = agent
    row["Skills"] = skills
    return row


def test_backfill_rows_clears_skills_when_both_populated():
    rows = [
        _row(agent="backend-implementer", skills="agents:backend-implementer.agent"),
        _row(agent="backend-implementer", skills=""),
        _row(agent="", skills="code-explainer:code-explainer"),
    ]

    changed = backfill.backfill_rows(rows)

    assert changed == 1
    assert rows[0]["Agent"] == "backend-implementer"
    assert rows[0]["Skills"] == ""
    assert rows[1]["Skills"] == ""
    assert rows[2]["Skills"] == "code-explainer:code-explainer"


def test_backfill_csv_rewrites_file_only_when_changed(tmp_path):
    csv_path = tmp_path / "records.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerow(_row(agent="backend-implementer", skills="agents:backend-implementer.agent"))
        writer.writerow(_row(agent="", skills="code-explainer:code-explainer"))

    changed = backfill.backfill_csv(str(csv_path))

    assert changed == 1
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["Agent"] == "backend-implementer"
    assert rows[0]["Skills"] == ""
    assert rows[1]["Skills"] == "code-explainer:code-explainer"


def test_backfill_csv_missing_file_is_a_noop(tmp_path):
    assert backfill.backfill_csv(str(tmp_path / "missing.csv")) == 0


def test_backfill_record_clears_skills_when_agent_present():
    record = {"Agent": "backend-implementer", "Skills": "agents:backend-implementer.agent"}
    assert backfill.backfill_record(record) is True
    assert record["Skills"] is None


def test_backfill_record_leaves_skill_only_record_unchanged():
    record = {"Agent": None, "Skills": "code-explainer:code-explainer"}
    assert backfill.backfill_record(record) is False
    assert record["Skills"] == "code-explainer:code-explainer"


def test_backfill_json_files_rewrites_session_records_in_place(tmp_path):
    session_dir = tmp_path / "003ed25f-cd28-4c09-a110-00cc92bcd293"
    session_dir.mkdir()
    polluted_path = session_dir / "20260715T062648227Z_req_1.json"
    clean_path = session_dir / "20260715T062700000Z_req_2.json"
    with open(polluted_path, "w", encoding="utf-8") as f:
        json.dump({"Agent": "backend-implementer", "Skills": "agents:backend-implementer.agent"}, f)
    with open(clean_path, "w", encoding="utf-8") as f:
        json.dump({"Agent": None, "Skills": "code-explainer:code-explainer"}, f)

    changed = backfill.backfill_json_files(str(tmp_path))

    assert changed == 1
    with open(polluted_path, encoding="utf-8") as f:
        assert json.load(f)["Skills"] is None
    with open(clean_path, encoding="utf-8") as f:
        assert json.load(f)["Skills"] == "code-explainer:code-explainer"


def test_backfill_json_files_skips_api_payloads_directory(tmp_path):
    payloads_dir = tmp_path / "api_payloads"
    payloads_dir.mkdir()
    payload_path = payloads_dir / "some_session_req_1.json"
    payload = {"agent": "backend-implementer", "skills": "agents:backend-implementer.agent"}
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    changed = backfill.backfill_json_files(str(tmp_path))

    assert changed == 0
    with open(payload_path, encoding="utf-8") as f:
        assert json.load(f) == payload
