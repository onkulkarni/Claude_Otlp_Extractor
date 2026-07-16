import csv
import json
import os

from extractor import api_payloads

FIELDS = [
    "Session ID", "Session Date", "Model", "Agent", "Skills", "JIRA Key", "User Email",
    "Cost USD", "Input Tokens", "Output Tokens", "Cache Read Tokens", "Cache Creation Tokens",
    "Request Count", "Request IDs",
]


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _row(session_id, request_ids, model="claude-sonnet-5", agent="claude-code", skills="docx",
         jira="APA-1", date="2026-07-10", email="onkar.kulkarni@nice.com", cost="0.42",
         in_tok="1200", out_tok="800", cache_read="300", cache_create="100", request_count="1"):
    return {
        "Session ID": session_id, "Session Date": date, "Model": model, "Agent": agent,
        "Skills": skills, "JIRA Key": jira, "User Email": email, "Cost USD": cost,
        "Input Tokens": in_tok, "Output Tokens": out_tok, "Cache Read Tokens": cache_read,
        "Cache Creation Tokens": cache_create, "Request Count": request_count, "Request IDs": request_ids,
    }


def test_build_payload_field_mapping_and_coercion():
    row = _row("sess-001", "req_1;req_2")

    payload = api_payloads.build_payload(row)

    assert payload == {
        "sessionId": "sess-001",
        "sessionDate": "2026-07-10T00:00:00.000Z",
        "model": "claude-sonnet-5",
        "agent": "claude-code",
        "emailId": "onkar.kulkarni@nice.com",
        "skills": "docx",
        "costUsd": 0.42,
        "inputTokens": 1200,
        "outputTokens": 800,
        "cacheReadTokens": 300,
        "cacheCreationTokens": 100,
        "jiraKey": "APA-1",
    }
    assert isinstance(payload["costUsd"], float)
    assert isinstance(payload["inputTokens"], int)


def test_build_payload_empty_skills_becomes_empty_string():
    row = _row("sess-001", "req_1", skills="")

    payload = api_payloads.build_payload(row)

    assert payload["skills"] == ""


def test_first_request_id_splits_on_semicolon():
    row = _row("sess-001", "req_1;req_2;req_3")

    assert api_payloads.first_request_id(row) == "req_1"


def test_first_request_id_single_value():
    row = _row("sess-001", "req_1")

    assert api_payloads.first_request_id(row) == "req_1"


def test_write_payloads_writes_one_file_per_row(tmp_path):
    csv_path = os.path.join(tmp_path, "records_consolidated.csv")
    output_dir = os.path.join(tmp_path, "api_payloads")
    _write_csv(csv_path, [
        _row("sess-001", "req_1", jira="APA-1"),
        _row("sess-002", "req_2", jira="APA-2"),
    ])

    written_paths = api_payloads.write_payloads(csv_path, output_dir)

    assert len(written_paths) == 2
    written_files = sorted(os.listdir(output_dir))
    assert written_files == ["sess-001_req_1.json", "sess-002_req_2.json"]

    with open(os.path.join(output_dir, "sess-001_req_1.json"), encoding="utf-8") as f:
        payload = json.load(f)
    assert payload["sessionId"] == "sess-001"
    assert payload["jiraKey"] == "APA-1"


def test_write_payloads_full_overwrite_removes_stale_files(tmp_path):
    csv_path = os.path.join(tmp_path, "records_consolidated.csv")
    output_dir = os.path.join(tmp_path, "api_payloads")
    os.makedirs(output_dir)
    stale_path = os.path.join(output_dir, "stale-session_req_old.json")
    with open(stale_path, "w", encoding="utf-8") as f:
        f.write("{}")

    _write_csv(csv_path, [
        _row("sess-001", "req_1", jira="APA-1"),
    ])

    written_paths = api_payloads.write_payloads(csv_path, output_dir)

    assert not os.path.exists(stale_path)
    assert len(written_paths) == 1
    assert os.listdir(output_dir) == ["sess-001_req_1.json"]


def test_missing_csv_load_rows_returns_empty():
    assert api_payloads.load_rows("does_not_exist.csv") == []


def test_missing_csv_write_payloads_writes_nothing(tmp_path):
    csv_path = os.path.join(tmp_path, "does_not_exist.csv")
    output_dir = os.path.join(tmp_path, "api_payloads")

    written_paths = api_payloads.write_payloads(csv_path, output_dir)

    assert written_paths == []
    assert os.listdir(output_dir) == []
