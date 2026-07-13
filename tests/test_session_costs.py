import csv
import os

from extractor.session_costs import load_session_costs

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


def _row(session_id, cost, request_id):
    return {
        "Session ID": session_id, "Session Date": "2026-07-10", "Model": "claude-sonnet-5",
        "Agent": "", "Skills": "", "Cost USD": cost, "Input Tokens": 1, "Output Tokens": 1,
        "Cache Read Tokens": 0, "Cache Creation Tokens": 0, "JIRA Key": "", "User Email": "",
        "Request ID": request_id,
    }


def test_sums_cost_per_session(tmp_path):
    csv_path = os.path.join(tmp_path, "records.csv")
    _write_csv(csv_path, [
        _row("s1", "0.01", "req_1"),
        _row("s1", "0.02", "req_2"),
        _row("s2", "0.05", "req_3"),
    ])

    totals = load_session_costs(csv_path)

    assert totals["s1"] == 0.03
    assert totals["s2"] == 0.05


def test_dedupes_duplicate_request_ids(tmp_path):
    csv_path = os.path.join(tmp_path, "records.csv")
    _write_csv(csv_path, [
        _row("s1", "0.01", "req_1"),
        _row("s1", "0.01", "req_1"),  # retried export batch, same request
    ])

    totals = load_session_costs(csv_path)

    assert totals["s1"] == 0.01
