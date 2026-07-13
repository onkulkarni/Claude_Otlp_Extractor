import csv
import os

from extractor import writer


def _record(request_id="req_1", session_id="sess-1", ts="2026-07-10T13:22:45.797Z", jira="APA-43308"):
    return {
        "Session ID": session_id,
        "Session Date": "2026-07-10",
        "Model": "claude-sonnet-5",
        "Agent": None,
        "Skills": None,
        "Cost USD": 0.01,
        "Input Tokens": 100,
        "Output Tokens": 20,
        "Cache Read Tokens": 0,
        "Cache Creation Tokens": 0,
        "JIRA Key": jira,
        "User Email": "onkar.kulkarni@nice.com",
        "_meta": {
            "request_id": request_id,
            "prompt_id": "prompt-1",
            "query_source": "repl_main_thread",
            "source_file": "logs/fixture.json",
            "event_timestamp": ts,
        },
    }


def test_write_record_creates_csv_with_header_on_first_write(tmp_path):
    output_dir = str(tmp_path / "extracted")
    csv_path = str(tmp_path / "extracted" / "records.csv")

    writer.write_record(output_dir, _record(), csv_path=csv_path)

    assert os.path.exists(csv_path)
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == writer.CSV_FIELDS
    assert len(rows) == 2  # header + 1 data row


def test_write_record_appends_without_duplicating_header(tmp_path):
    output_dir = str(tmp_path / "extracted")
    csv_path = str(tmp_path / "extracted" / "records.csv")

    writer.write_record(output_dir, _record(request_id="req_1"), csv_path=csv_path)
    writer.write_record(output_dir, _record(request_id="req_2", ts="2026-07-10T13:23:00.000Z"), csv_path=csv_path)

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows.count(writer.CSV_FIELDS) == 1  # header written exactly once
    assert len(rows) == 3  # header + 2 data rows


def test_no_csv_row_appended_when_json_already_written(tmp_path):
    output_dir = str(tmp_path / "extracted")
    csv_path = str(tmp_path / "extracted" / "records.csv")

    record = _record(request_id="req_dup")
    first_path = writer.write_record(output_dir, record, csv_path=csv_path)
    second_path = writer.write_record(output_dir, record, csv_path=csv_path)

    assert first_path is not None
    assert second_path is None  # idempotent JSON skip

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2  # header + exactly 1 data row, no duplicate on re-run


def test_csv_row_values_match_record(tmp_path):
    output_dir = str(tmp_path / "extracted")
    csv_path = str(tmp_path / "extracted" / "records.csv")

    writer.write_record(output_dir, _record(request_id="req_x", jira="APA-99999"), csv_path=csv_path)

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["JIRA Key"] == "APA-99999"
    assert rows[0]["Request ID"] == "req_x"
    assert rows[0]["Model"] == "claude-sonnet-5"


def test_write_record_without_csv_path_skips_csv_entirely(tmp_path):
    output_dir = str(tmp_path / "extracted")
    path = writer.write_record(output_dir, _record(), csv_path=None)
    assert path is not None
    assert not os.path.exists(os.path.join(output_dir, "records.csv"))
