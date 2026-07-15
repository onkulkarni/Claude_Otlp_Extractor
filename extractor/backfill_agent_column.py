"""One-off backfill for records.csv rows written before extract_agent_from_skill_name
existed: an `agents:<name>.agent` value that was dumped into Skills is moved into
Agent (Skills cleared for that row).

Read-modify-write over records.csv, following the same pattern as
extractor/consolidate.py. After running this, regenerate the downstream reports:
`python -m extractor.consolidate` and `python -m extractor.api_payloads`.
"""

import argparse
import csv
import os

from extractor.agent import extract_agent_from_skill_name
from extractor.correlate import OUTPUT_FIELDS

CSV_FIELDS = OUTPUT_FIELDS + ["Request ID"]


def backfill_rows(rows: list[dict]) -> int:
    changed = 0
    for row in rows:
        agent_value = extract_agent_from_skill_name(row.get("Skills"))
        if agent_value and not row.get("Agent"):
            row["Agent"] = agent_value
            row["Skills"] = ""
            changed += 1
    return changed


def backfill_csv(csv_path: str) -> int:
    if not os.path.exists(csv_path):
        return 0

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    changed = backfill_rows(rows)

    if changed:
        tmp_path = f"{csv_path}.tmp"
        with open(tmp_path, "w", newline="", encoding="utf-8") as f:
            csv_writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            csv_writer.writeheader()
            csv_writer.writerows(rows)
        os.replace(tmp_path, csv_path)

    return changed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill records.csv rows where an agents:*.agent value was "
        "incorrectly written to Skills instead of Agent."
    )
    parser.add_argument("--csv-path", default="extracted/records.csv", help="Path to records.csv")
    args = parser.parse_args(argv)

    changed = backfill_csv(args.csv_path)
    print(f"Backfilled {changed} row(s) in {args.csv_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
