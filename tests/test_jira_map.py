import csv
import os

from extractor import jira_map

FIELDS = [
    "Session ID", "Session Date", "Model", "Agent", "Skills", "Cost USD",
    "Input Tokens", "Output Tokens", "Cache Read Tokens", "Cache Creation Tokens",
    "JIRA Key", "User Email", "Request ID",
]


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _row(session_id, request_id, jira=""):
    return {
        "Session ID": session_id, "Session Date": "2026-07-10", "Model": "claude-sonnet-5",
        "Agent": "", "Skills": "", "Cost USD": "0.01", "Input Tokens": "1", "Output Tokens": "1",
        "Cache Read Tokens": "0", "Cache Creation Tokens": "0", "JIRA Key": jira, "User Email": "",
        "Request ID": request_id,
    }


def test_build_from_csv_basic(tmp_path):
    csv_path = os.path.join(tmp_path, "records.csv")
    _write_csv(csv_path, [
        _row("s1", "req_1", jira="APA-1"),
        _row("s2", "req_2", jira="APA-2"),
    ])

    result = jira_map.build_from_csv(csv_path)

    assert result == {"s1": "APA-1", "s2": "APA-2"}


def test_build_from_csv_last_non_null_wins(tmp_path):
    csv_path = os.path.join(tmp_path, "records.csv")
    _write_csv(csv_path, [
        _row("s1", "req_1", jira="APA-1"),
        _row("s1", "req_2", jira=""),  # non-matching prompt, JIRA Key empty on this row
        _row("s1", "req_3", jira="APA-2"),
    ])

    result = jira_map.build_from_csv(csv_path)

    assert result == {"s1": "APA-2"}


def test_build_from_csv_missing_file_returns_empty_dict(tmp_path):
    csv_path = os.path.join(tmp_path, "does_not_exist.csv")
    assert jira_map.build_from_csv(csv_path) == {}


def test_save_and_load_roundtrip(tmp_path):
    path = os.path.join(tmp_path, "sub", "session_jira_map.json")
    data = {"s1": "APA-1", "s2": "APA-2"}

    jira_map.save(path, data)
    loaded = jira_map.load(path)

    assert loaded == data


def test_load_missing_file_returns_empty_dict(tmp_path):
    path = os.path.join(tmp_path, "does_not_exist.json")
    assert jira_map.load(path) == {}
