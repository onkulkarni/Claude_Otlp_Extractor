"""Generate one JSON API payload file per row of records_consolidated.csv,
shaped to match the server's target contract (see plans/2026-07-15-api-payloads.md).

Read-only report over records_consolidated.csv, following the same pattern as
extractor/consolidate.py and extractor/session_costs.py. Does not send any HTTP
requests -- that is a separate, future piece of work.
"""

import argparse
import csv
import glob
import json
import os


def load_rows(csv_path: str) -> list[dict]:
    if not os.path.exists(csv_path):
        return []

    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def first_request_id(row: dict) -> str:
    return row["Request IDs"].split(";")[0]


def build_payload(row: dict) -> dict:
    return {
        "sessionId": row["Session ID"],
        "sessionDate": f"{row['Session Date']}T00:00:00.000Z",
        "model": row.get("Model"),
        "agent": row.get("Agent"),
        "emailId": row.get("User Email"),
        "skills": row.get("Skills") or "",
        "costUsd": float(row.get("Cost USD") or 0),
        "inputTokens": int(row.get("Input Tokens") or 0),
        "outputTokens": int(row.get("Output Tokens") or 0),
        "cacheReadTokens": int(row.get("Cache Read Tokens") or 0),
        "cacheCreationTokens": int(row.get("Cache Creation Tokens") or 0),
        "jiraKey": row.get("JIRA Key"),
    }


def write_payloads(csv_path: str, output_dir: str) -> list[str]:
    rows = load_rows(csv_path)

    os.makedirs(output_dir, exist_ok=True)
    for stale_path in glob.glob(os.path.join(output_dir, "*.json")):
        os.remove(stale_path)

    written_paths = []
    for row in rows:
        payload = build_payload(row)
        filename = f"{row['Session ID']}_{first_request_id(row)}.json"
        path = os.path.join(output_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        written_paths.append(path)

    return written_paths


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate one JSON API payload file per row of records_consolidated.csv."
    )
    parser.add_argument(
        "--csv-path", default="extracted/records_consolidated.csv", help="Path to records_consolidated.csv"
    )
    parser.add_argument(
        "--output-dir", default="extracted/api_payloads", help="Directory to write JSON payload files"
    )
    args = parser.parse_args(argv)

    rows = load_rows(args.csv_path)
    written_paths = write_payloads(args.csv_path, args.output_dir)

    for row in rows:
        payload = build_payload(row)
        print(
            f"{payload['sessionId']}\t{payload['jiraKey']}\t{payload['model']}\t${payload['costUsd']:.4f}"
        )
    print(f"Wrote {len(written_paths)} payload file(s) to {args.output_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
