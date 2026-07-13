"""Write one output record per api_request event."""

import csv
import glob
import json
import os

from extractor.correlate import OUTPUT_FIELDS

CSV_FIELDS = OUTPUT_FIELDS + ["Request ID"]


def _compact_timestamp(iso_ts: str) -> str:
    return iso_ts.replace(":", "").replace("-", "").replace(".", "")


def already_written(output_dir: str, session_id: str, request_id: str) -> bool:
    session_dir = os.path.join(output_dir, session_id)
    pattern = os.path.join(session_dir, f"*_{request_id}.json")
    return len(glob.glob(pattern)) > 0


def append_csv_row(csv_path: str, record: dict) -> None:
    parent = os.path.dirname(csv_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    file_exists = os.path.exists(csv_path)

    row = {field: record.get(field) for field in OUTPUT_FIELDS}
    row["Request ID"] = record["_meta"]["request_id"]

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        csv_writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            csv_writer.writeheader()
        csv_writer.writerow(row)
        f.flush()


def write_record(output_dir: str, record: dict, csv_path: str | None = None) -> str | None:
    session_id = record["Session ID"]
    request_id = record["_meta"]["request_id"]
    if already_written(output_dir, session_id, request_id):
        return None

    session_dir = os.path.join(output_dir, session_id)
    os.makedirs(session_dir, exist_ok=True)

    ts = _compact_timestamp(record["_meta"]["event_timestamp"])
    path = os.path.join(session_dir, f"{ts}_{request_id}.json")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)

    if csv_path is not None:
        append_csv_row(csv_path, record)

    return path
