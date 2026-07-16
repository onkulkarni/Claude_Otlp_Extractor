"""One-off backfill enforcing the Agent-implies-no-Skills invariant on already
extracted data: any row/record with both `Agent` and `Skills` non-empty gets
`Skills` cleared. Covers state polluted before `_build_record()` started
enforcing this at build time (see extracted/records.csv session
003ed25f-cd28-4c09-a110-00cc92bcd293).

Backfills both `records.csv` and the per-record JSON files under
extracted/<session_id>/*.json, following the same read-modify-write pattern as
extractor/backfill_agent_column.py. After running this, regenerate the
downstream reports: `python -m extractor.consolidate` and
`python -m extractor.api_payloads`.
"""

import argparse
import csv
import glob
import json
import os

from extractor.correlate import OUTPUT_FIELDS

CSV_FIELDS = OUTPUT_FIELDS + ["Request ID"]


def backfill_rows(rows: list[dict]) -> int:
    changed = 0
    for row in rows:
        if row.get("Agent") and row.get("Skills"):
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


def backfill_record(record: dict) -> bool:
    if record.get("Agent") and record.get("Skills"):
        record["Skills"] = None
        return True
    return False


EXCLUDED_SUBDIRS = {"api_payloads"}


def backfill_json_files(extracted_dir: str) -> int:
    changed = 0
    pattern = os.path.join(extracted_dir, "*", "*.json")
    for path in glob.glob(pattern):
        session_dir = os.path.basename(os.path.dirname(path))
        if session_dir in EXCLUDED_SUBDIRS:
            continue

        with open(path, "r", encoding="utf-8") as f:
            record = json.load(f)

        if backfill_record(record):
            changed += 1
            tmp_path = f"{path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2)
            os.replace(tmp_path, path)

    return changed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill records.csv rows and per-record JSON files where "
        "Agent and Skills are both populated, clearing Skills."
    )
    parser.add_argument("--csv-path", default="extracted/records.csv", help="Path to records.csv")
    parser.add_argument(
        "--extracted-dir",
        default="extracted",
        help="Directory containing per-session subdirectories of per-record JSON files",
    )
    args = parser.parse_args(argv)

    csv_changed = backfill_csv(args.csv_path)
    print(f"Backfilled {csv_changed} row(s) in {args.csv_path}")

    json_changed = backfill_json_files(args.extracted_dir)
    print(f"Backfilled {json_changed} per-record JSON file(s) under {args.extracted_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
