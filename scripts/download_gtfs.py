from __future__ import annotations

import argparse
import logging
import sys
import zipfile
from pathlib import Path

import requests

from backend.app.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

GTFS_URL = "https://eu.ftp.opendatasoft.com/stif/GTFS/IDFM-gtfs.zip"
RAW_DIR = PROJECT_ROOT / "backend" / "data" / "raw"
ZIP_PATH = RAW_DIR / "IDFM-gtfs.zip"
EXTRACT_DIR = RAW_DIR / "gtfs"

REQUIRED_FILES: tuple[str, ...] = (
    "stops.txt",
    "routes.txt",
    "trips.txt",
    "stop_times.txt",
)

CHUNK_SIZE = 1024 * 256  # 256 KiB


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url}")
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with dest.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if not chunk:
                    continue
                fh.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    print(f"\r  {downloaded / 1e6:6.1f} / {total / 1e6:.1f} MB ({pct:3d}%)", end="")
                else:
                    print(f"\r  {downloaded / 1e6:6.1f} MB", end="")
        print()
    print(f"Saved to {dest}")


def extract(zip_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Extracting {zip_path.name} -> {out_dir}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(out_dir, filter="data")
    print(f"Extracted {len(list(out_dir.iterdir()))} entries.")


def validate(out_dir: Path) -> bool:
    missing = [name for name in REQUIRED_FILES if not (out_dir / name).is_file()]
    if missing:
        logger.warning("Missing required GTFS files: %s", ", ".join(missing))
        return False
    return True


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Download and extract IDFM GTFS.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download and re-extract even if files already exist.",
    )
    args = parser.parse_args()

    if args.force or not ZIP_PATH.is_file():
        download(GTFS_URL, ZIP_PATH)
    else:
        print(f"Zip already present at {ZIP_PATH}; use --force to re-download.")

    if args.force or not validate(EXTRACT_DIR):
        extract(ZIP_PATH, EXTRACT_DIR)

    if not validate(EXTRACT_DIR):
        print("ERROR: GTFS extraction is missing required files.", file=sys.stderr)
        return 1

    print(f"GTFS ready at {EXTRACT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
