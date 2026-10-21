#!/usr/bin/env python
"""Download the workshop datasets from the public Kaggle files (no account, no API key).

    python scripts/fetch_data.py                 # both datasets, about 0.45 GB download
    python scripts/fetch_data.py by_minute       # only the 23 MB by-minute file
    python scripts/fetch_data.py --pin           # maintainers: record checksums in data/checksums.json

Skip this script to use the small sample committed in data/sample (smoke-test mode).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lolml import data  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("names", nargs="*", choices=list(data.SOURCES))
ap.add_argument("--no-verify", action="store_true", help="accept data that does not match data/checksums.json")
ap.add_argument("--pin", action="store_true", help="record checksum and row count of what was downloaded")
a = ap.parse_args()

pins = json.loads(data.CHECKSUMS.read_text()) if data.CHECKSUMS.exists() else {}
for n in a.names or list(data.SOURCES):
    info = data.fetch(n, verify=not (a.pin or a.no_verify))
    if a.pin:
        pins[n] = info
        data.CHECKSUMS.write_text(json.dumps(pins, indent=2) + "\n")
        print(f"[{n}] pinned in {data.CHECKSUMS}")
