"""CLI entrypoint: python -m extractor --input received --output extracted [--dry-run]"""

import argparse
import os

from extractor import correlate, writer


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Extract OTLP Claude Code records to per-record JSON files.")
    parser.add_argument("--input", required=True, help="Input folder containing logs/, metrics/, traces/ subfolders")
    parser.add_argument("--output", required=True, help="Output folder for extracted/<session_id>/<...>.json files")
    parser.add_argument("--state-dir", default=".state", help="Folder for persisted per-session correlation state")
    parser.add_argument("--csv-path", default=None, help="CSV file to append one row to per record (default: <output>/records.csv)")
    parser.add_argument("--dry-run", action="store_true", help="Print would-be-emitted records instead of writing files")
    args = parser.parse_args(argv)

    csv_path = args.csv_path or os.path.join(args.output, "records.csv")

    records = correlate.run(args.input, args.state_dir)

    written = 0
    skipped = 0
    for record in records:
        meta = record["_meta"]
        if args.dry_run:
            print(
                f"{record['Session ID']}\t{meta['request_id']}\t{record['Model']}\t"
                f"{record['Cost USD']}\t{record['JIRA Key']}\t{record['Skills']}\t{record['Agent']}"
            )
            continue
        path = writer.write_record(args.output, record, csv_path=csv_path)
        if path is None:
            skipped += 1
        else:
            written += 1

    if not args.dry_run:
        print(f"Wrote {written} record(s), skipped {skipped} already-written (idempotent).")
    else:
        print(f"Dry run: {len(records)} record(s) would be emitted.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
