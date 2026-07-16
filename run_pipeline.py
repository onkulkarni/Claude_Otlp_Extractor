"""Production pipeline: extract -> consolidate -> generate API payloads.

Runs against the project's real received/, extracted/, and .state/ folders,
using whichever Python interpreter is running this script. Cross-platform
(Windows/macOS/Linux) since it shells out via subprocess instead of relying on
a shell-specific script.

Idempotent: `python -m extractor` skips any request_id already extracted, so
re-running this after new logs land under received/logs/ only picks up the
new ones -- nothing already on disk gets duplicated or overwritten.

Usage: python run_pipeline.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

STEPS = [
    ("Extracting records from received/ into extracted/",
     [sys.executable, "-m", "extractor", "--input", "received", "--output", "extracted", "--state-dir", ".state"]),
    ("Consolidating extracted/records.csv",
     [sys.executable, "-m", "extractor.consolidate"]),
    ("Generating API payloads",
     [sys.executable, "-m", "extractor.api_payloads"]),
    ("Invoking API with generated payloads",
     [sys.executable, "invoker.py", "--config", "config.yaml"]),
]


def main() -> int:
    total = len(STEPS)
    for i, (description, cmd) in enumerate(STEPS, start=1):
        print(f"\n== {i}/{total}: {description} ==", flush=True)
        result = subprocess.run(cmd, cwd=ROOT)
        if result.returncode != 0:
            print(f"\nStep {i} failed with exit code {result.returncode}: {' '.join(cmd)}", file=sys.stderr, flush=True)
            return result.returncode

    print("\nPipeline complete.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
