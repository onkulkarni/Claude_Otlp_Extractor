"""Sum 'Cost USD' per session from records.csv, plus a grand total.

Dedupes on Request ID (the natural idempotency key per writer.py/HANDOFF.md)
before summing, in case records.csv was assembled from overlapping runs.
"""

import argparse
import csv
from collections import defaultdict


def load_session_costs(csv_path: str) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    seen_request_ids: set[str] = set()

    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            request_id = row["Request ID"]
            if request_id in seen_request_ids:
                continue
            seen_request_ids.add(request_id)
            totals[row["Session ID"]] += float(row["Cost USD"])

    return dict(totals)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sum Cost USD per session from records.csv.")
    parser.add_argument("--csv-path", default="extracted/records.csv", help="Path to records.csv")
    args = parser.parse_args(argv)

    totals = load_session_costs(args.csv_path)

    grand_total = 0.0
    for session_id in sorted(totals):
        cost = totals[session_id]
        grand_total += cost
        print(f"{session_id}\t${cost:.4f}")
    print(f"TOTAL\t${grand_total:.4f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
