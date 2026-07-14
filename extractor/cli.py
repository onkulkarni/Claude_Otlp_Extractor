"""CLI entrypoint: python -m extractor --input received --output extracted [--dry-run] [--interval SECONDS]"""

import argparse
import os
import time
from datetime import datetime, timezone

from extractor import correlate, jira_map, writer


def run_once(args) -> tuple[int, int]:
    csv_path = args.csv_path or os.path.join(args.output, "records.csv")
    jira_map_path = args.jira_map_path or os.path.join(args.output, "session_jira_map.json")

    jira_fallback = jira_map.build_from_csv(csv_path)
    records = correlate.run(args.input, args.state_dir, jira_fallback=jira_fallback)

    written = 0
    skipped = 0
    for record in records:
        meta = record["_meta"]
        if args.dry_run:
            print(
                f"{record['Session ID']}\t{meta['request_id']}\t{record['Model']}\t"
                f"{record['Cost USD']}\t{record['JIRA Key']}\t{record['Skills']}\t{record['Agent']}"
            )
            written += 1
            continue
        path = writer.write_record(args.output, record, csv_path=csv_path)
        if path is None:
            skipped += 1
        else:
            written += 1

    if args.dry_run:
        print(f"Dry run: {written} record(s) would be emitted.")
    else:
        print(f"Wrote {written} record(s), skipped {skipped} already-written (idempotent).")
        # Rebuild from the just-updated CSV so the fallback snapshot stays current.
        jira_map.save(jira_map_path, jira_map.build_from_csv(csv_path))

    return written, skipped


def run_interval(args, sleep_fn=time.sleep) -> int:
    cycle = 0
    try:
        while True:
            cycle += 1
            written, skipped = run_once(args)
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            print(f"[{now}] cycle {cycle}: wrote {written}, skipped {skipped}")
            sleep_fn(args.interval)
    except KeyboardInterrupt:
        print(f"Interval loop stopped after {cycle} cycle(s).")
        return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Extract OTLP Claude Code records to per-record JSON files.")
    parser.add_argument("--input", required=True, help="Input folder containing logs/, metrics/, traces/ subfolders")
    parser.add_argument("--output", required=True, help="Output folder for extracted/<session_id>/<...>.json files")
    parser.add_argument("--state-dir", default=".state", help="Folder for persisted per-session correlation state")
    parser.add_argument("--csv-path", default=None, help="CSV file to append one row to per record (default: <output>/records.csv)")
    parser.add_argument(
        "--jira-map-path", default=None,
        help="Session->JIRA resume map JSON path (default: <output>/session_jira_map.json)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print would-be-emitted records instead of writing files")
    parser.add_argument(
        "--interval", type=float, default=None,
        help="Re-run every SECONDS, unattended, until interrupted with Ctrl+C (default: run once and exit)",
    )
    args = parser.parse_args(argv)

    if args.interval is None:
        run_once(args)
        return 0

    return run_interval(args)


if __name__ == "__main__":
    raise SystemExit(main())
