"""Consolidated session report: collapse consecutive records.csv rows into
one row per unbroken run of the same Model/Agent/Skills/JIRA Key, per session.

Read-only report over records.csv, following the same pattern as
extractor/session_costs.py — no changes to raw extraction output.
"""

import argparse
import csv
import os

GROUP_KEY_FIELDS = ["Model", "Agent", "Skills", "JIRA Key"]

CONSOLIDATED_FIELDS = [
    "Session ID", "Session Date", "Model", "Agent", "Skills", "JIRA Key", "User Email",
    "Cost USD", "Input Tokens", "Output Tokens", "Cache Read Tokens", "Cache Creation Tokens",
    "Request Count", "Request IDs",
]


def load_deduped_rows(csv_path: str) -> list[dict]:
    rows = []
    seen_request_ids: set[str] = set()

    if not os.path.exists(csv_path):
        return rows

    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            request_id = row["Request ID"]
            if request_id in seen_request_ids:
                continue
            seen_request_ids.add(request_id)
            rows.append(row)

    return rows


def _new_group(row: dict) -> dict:
    return {
        "Session ID": row["Session ID"],
        "Session Date": row.get("Session Date"),
        "Model": row.get("Model"),
        "Agent": row.get("Agent"),
        "Skills": row.get("Skills"),
        "JIRA Key": row.get("JIRA Key"),
        "User Email": row.get("User Email"),
        "Cost USD": 0.0,
        "Input Tokens": 0,
        "Output Tokens": 0,
        "Cache Read Tokens": 0,
        "Cache Creation Tokens": 0,
        "Request Count": 0,
        "Request IDs": [],
    }


def _accumulate(group: dict, row: dict) -> None:
    group["Cost USD"] += float(row.get("Cost USD") or 0)
    group["Input Tokens"] += int(row.get("Input Tokens") or 0)
    group["Output Tokens"] += int(row.get("Output Tokens") or 0)
    group["Cache Read Tokens"] += int(row.get("Cache Read Tokens") or 0)
    group["Cache Creation Tokens"] += int(row.get("Cache Creation Tokens") or 0)
    group["Request Count"] += 1
    group["Request IDs"].append(row["Request ID"])


def consolidate_records(csv_path: str) -> list[dict]:
    rows = load_deduped_rows(csv_path)

    # Rows for a session are already in event.sequence order (correlate.py
    # sorts (session_id, event.sequence) before emission, writer.py only
    # appends), so grouping by Session ID here preserves that order.
    rows_by_session: dict[str, list[dict]] = {}
    for row in rows:
        rows_by_session.setdefault(row["Session ID"], []).append(row)

    groups = []
    for session_rows in rows_by_session.values():
        current_key = None
        current_group = None
        for row in session_rows:
            key = tuple(row.get(field) for field in GROUP_KEY_FIELDS)
            if key != current_key:
                current_group = _new_group(row)
                groups.append(current_group)
                current_key = key
            _accumulate(current_group, row)

    for group in groups:
        group["Request IDs"] = ";".join(group["Request IDs"])

    return groups


def _write_csv(path: str, groups: list) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        csv_writer = csv.DictWriter(f, fieldnames=CONSOLIDATED_FIELDS)
        csv_writer.writeheader()
        for group in groups:
            csv_writer.writerow(group)
    os.replace(tmp_path, path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Consolidate records.csv into one row per unbroken run of Model/Agent/Skills/JIRA Key."
    )
    parser.add_argument("--csv-path", default="extracted/records.csv", help="Path to records.csv")
    parser.add_argument(
        "--output-path", default="extracted/records_consolidated.csv", help="Path to write consolidated CSV"
    )
    args = parser.parse_args(argv)

    groups = consolidate_records(args.csv_path)
    _write_csv(args.output_path, groups)

    for group in groups:
        print(
            f"{group['Session ID']}\t{group['Model']}\t{group['JIRA Key']}\t{group['Skills']}\t"
            f"{group['Agent']}\t${group['Cost USD']:.4f}\t{group['Request Count']} request(s)"
        )
    print(f"Wrote {len(groups)} consolidated row(s) to {args.output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
