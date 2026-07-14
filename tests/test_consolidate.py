import csv
import os

from extractor import consolidate, session_costs

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


def _row(session_id, request_id, model="claude-sonnet-5", agent="", skills="", jira="APA-1",
         date="2026-07-10", cost="0.01", in_tok="10", out_tok="5", cache_read="0", cache_create="0"):
    return {
        "Session ID": session_id, "Session Date": date, "Model": model,
        "Agent": agent, "Skills": skills, "Cost USD": cost, "Input Tokens": in_tok,
        "Output Tokens": out_tok, "Cache Read Tokens": cache_read, "Cache Creation Tokens": cache_create,
        "JIRA Key": jira, "User Email": "onkar.kulkarni@nice.com", "Request ID": request_id,
    }


def test_basic_grouping_and_summation(tmp_path):
    csv_path = os.path.join(tmp_path, "records.csv")
    _write_csv(csv_path, [
        _row("s1", "req_1", cost="0.01"),
        _row("s1", "req_2", cost="0.02"),
    ])

    groups = consolidate.consolidate_records(csv_path)

    assert len(groups) == 1
    assert groups[0]["Request Count"] == 2
    assert round(groups[0]["Cost USD"], 4) == 0.03
    assert groups[0]["Request IDs"] == "req_1;req_2"


def test_recurrence_does_not_re_merge(tmp_path):
    # tuple sequence A, A, B, A -> 3 groups, not 2
    csv_path = os.path.join(tmp_path, "records.csv")
    _write_csv(csv_path, [
        _row("s1", "req_1", jira="APA-1"),
        _row("s1", "req_2", jira="APA-1"),
        _row("s1", "req_3", jira="APA-2"),
        _row("s1", "req_4", jira="APA-1"),
    ])

    groups = consolidate.consolidate_records(csv_path)

    assert len(groups) == 3
    assert [g["JIRA Key"] for g in groups] == ["APA-1", "APA-2", "APA-1"]
    assert [g["Request Count"] for g in groups] == [2, 1, 1]


def test_session_date_uses_first_row_of_group(tmp_path):
    csv_path = os.path.join(tmp_path, "records.csv")
    _write_csv(csv_path, [
        _row("s1", "req_1", date="2026-07-10"),
        _row("s1", "req_2", date="2026-07-11"),  # group spans midnight
    ])

    groups = consolidate.consolidate_records(csv_path)

    assert len(groups) == 1
    assert groups[0]["Session Date"] == "2026-07-10"


def test_numeric_coercion_after_csv_roundtrip(tmp_path):
    csv_path = os.path.join(tmp_path, "records.csv")
    _write_csv(csv_path, [
        _row("s1", "req_1", cost="0.5", in_tok="100", out_tok="20", cache_read="30", cache_create="4"),
    ])

    groups = consolidate.consolidate_records(csv_path)

    assert groups[0]["Cost USD"] == 0.5
    assert groups[0]["Input Tokens"] == 100
    assert groups[0]["Output Tokens"] == 20
    assert groups[0]["Cache Read Tokens"] == 30
    assert groups[0]["Cache Creation Tokens"] == 4


def test_dedupes_by_request_id(tmp_path):
    csv_path = os.path.join(tmp_path, "records.csv")
    _write_csv(csv_path, [
        _row("s1", "req_1", cost="0.01"),
        _row("s1", "req_1", cost="0.01"),  # retried export batch, same request
    ])

    groups = consolidate.consolidate_records(csv_path)

    assert len(groups) == 1
    assert groups[0]["Request Count"] == 1
    assert round(groups[0]["Cost USD"], 4) == 0.01


def test_group_costs_cross_check_against_session_costs(tmp_path):
    csv_path = os.path.join(tmp_path, "records.csv")
    _write_csv(csv_path, [
        _row("s1", "req_1", jira="APA-1", cost="0.01"),
        _row("s1", "req_2", jira="APA-2", cost="0.02"),
        _row("s1", "req_3", jira="APA-1", cost="0.03"),
        _row("s2", "req_4", jira="APA-3", cost="0.05"),
    ])

    groups = consolidate.consolidate_records(csv_path)
    totals = session_costs.load_session_costs(csv_path)

    summed_by_session: dict[str, float] = {}
    for group in groups:
        summed_by_session[group["Session ID"]] = summed_by_session.get(group["Session ID"], 0.0) + group["Cost USD"]

    for session_id, total in totals.items():
        assert round(summed_by_session[session_id], 6) == round(total, 6)


def test_missing_csv_returns_no_groups(tmp_path):
    csv_path = os.path.join(tmp_path, "does_not_exist.csv")
    assert consolidate.consolidate_records(csv_path) == []
