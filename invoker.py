import argparse
import logging
import sys
import time
from pathlib import Path

import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("invoker")


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def send_payload(url, method, headers, raw_body):
    return requests.request(method, url, headers=headers, data=raw_body, timeout=30)


def main():
    parser = argparse.ArgumentParser(description="POST each JSON file in a directory to an API, one request per file.")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    args = parser.parse_args()

    config = load_config(args.config)
    api_cfg = config["api"]
    url = api_cfg["url"]
    method = api_cfg.get("method", "POST")
    headers = api_cfg.get("headers", {})
    payloads_dir = Path(config["payloads_dir"])

    files = sorted(payloads_dir.glob("*.json"))
    if not files:
        log.warning("No JSON files found in %s", payloads_dir)

    succeeded = []
    failed = []

    for file_path in files:
        raw_body = file_path.read_bytes()
        start = time.monotonic()
        try:
            response = send_payload(url, method, headers, raw_body)
            elapsed = time.monotonic() - start
            if 200 <= response.status_code < 300:
                log.info("OK   %s -> %s (%.2fs)", file_path.name, response.status_code, elapsed)
                succeeded.append(file_path.name)
            else:
                log.error("FAIL %s -> %s (%.2fs): %s", file_path.name, response.status_code, elapsed, response.text[:500])
                failed.append(file_path.name)
        except requests.RequestException as exc:
            elapsed = time.monotonic() - start
            log.error("FAIL %s -> exception after %.2fs: %s", file_path.name, elapsed, exc)
            failed.append(file_path.name)

    log.info("Summary: %d succeeded, %d failed (of %d total)", len(succeeded), len(failed), len(files))
    if failed:
        log.info("Failed files: %s", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
