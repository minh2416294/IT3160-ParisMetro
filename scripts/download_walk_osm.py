from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests

from backend.app.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
RAW_DIR = PROJECT_ROOT / "backend" / "data" / "raw"
OUT_PATH = RAW_DIR / "walk.osm.json"

# Central Paris bounding box (south, west, north, east).
BBOX = (48.82, 2.27, 48.90, 2.42)

WALKABLE_HIGHWAYS = (
    "footway",
    "pedestrian",
    "path",
    "living_street",
    "residential",
    "service",
    "sidewalk",
    "steps",
    "unclassified",
)

USER_AGENT = "ParisMetroNavigator/0.1 (IT3160 coursework)"


def build_query(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    regex = "|".join(WALKABLE_HIGHWAYS)
    return f"""
[out:json][timeout:180];
(
  way["highway"~"^({regex})$"]({s},{w},{n},{e});
);
(._;>;);
out body;
""".strip()


def download(query: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Querying Overpass ({OVERPASS_URL})")
    resp = requests.post(
        OVERPASS_URL,
        data={"data": query},
        headers={"User-Agent": USER_AGENT},
        timeout=300,
    )
    resp.raise_for_status()
    payload = resp.json()
    dest.write_text(json.dumps(payload), encoding="utf-8")

    elements = payload.get("elements", [])
    nodes = sum(1 for el in elements if el.get("type") == "node")
    ways = sum(1 for el in elements if el.get("type") == "way")
    print(f"Saved {dest} ({nodes} nodes, {ways} ways, {dest.stat().st_size / 1e6:.1f} MB)")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Download central-Paris walking graph from OSM via Overpass.")
    parser.add_argument("--force", action="store_true", help="Re-download even if file exists.")
    args = parser.parse_args()

    if OUT_PATH.is_file() and not args.force:
        print(f"Already present: {OUT_PATH}; use --force to re-download.")
        return 0

    query = build_query(BBOX)
    download(query, OUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
