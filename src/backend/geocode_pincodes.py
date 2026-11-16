"""Give every pincode in config/regions.json a map position, using Google's Geocoding API.

    python src/backend/geocode_pincodes.py          # only pincodes without a position
    python src/backend/geocode_pincodes.py --all    # look every pincode up again

Needs GOOGLE_API_KEY in .env (Geocoding API enabled). Positions are written into regions.json
itself ("latitude"/"longitude" on each pincode line), so they survive a database rebuild. A result
more than 80 km from its region's centre is treated as a wrong match and skipped.
"""
import argparse
import json
import math
import re
import time
import urllib.parse
import urllib.request

import db
import env

URL = "https://maps.googleapis.com/maps/api/geocode/json"
MAX_KM = 80


def km(a, b) -> float:
    (la1, lo1), (la2, lo2) = a, b
    x = math.radians(lo2 - lo1) * math.cos(math.radians((la1 + la2) / 2))
    return 6371 * math.hypot(x, math.radians(la2 - la1))


def lookup(key: str, pincode: str, state: str) -> tuple[float, float] | None:
    for params in ({"components": f"postal_code:{pincode}|country:IN"},
                   {"address": f"{pincode}, {state}, India"}):
        q = urllib.parse.urlencode({**params, "key": key})
        with urllib.request.urlopen(f"{URL}?{q}", timeout=20) as r:
            d = json.load(r)
        if d["status"] == "OK":
            loc = d["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
        if d["status"] not in ("ZERO_RESULTS",):
            raise SystemExit(f"Google geocoding refused: {d['status']} {d.get('error_message', '')}")
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="look up pincodes that already have a position too")
    args = ap.parse_args()
    env.load_dotenv()
    key = env.require("GOOGLE_API_KEY")

    path = db.REGIONS_FILE
    config = json.loads(path.read_text())
    text = path.read_text()
    found, skipped, failed = 0, [], []
    for region in config["regions"]:
        centre = (region["centre"]["latitude"], region["centre"]["longitude"])
        for zone in region["zones"]:
            for district in zone["districts"]:
                for p in district["pincodes"]:
                    if "latitude" in p and not args.all:
                        continue
                    pos = lookup(key, p["code"], region["state"])
                    time.sleep(0.05)
                    if not pos:
                        failed.append(p["code"])
                        continue
                    if km(pos, centre) > MAX_KM:
                        skipped.append(f"{p['code']} ({km(pos, centre):.0f} km away)")
                        continue
                    # Edit the pincode's own line so the rest of the file keeps its layout.
                    line = re.compile(r'(\{ "code": "' + p["code"] + r'")(, "latitude": [-\d.]+, "longitude": [-\d.]+)?')
                    text, n = line.subn(rf'\1, "latitude": {pos[0]:.5f}, "longitude": {pos[1]:.5f}', text, count=1)
                    found += n
    json.loads(text)  # never write a file that no longer parses
    path.write_text(text)
    print(f"Positions written: {found}.")
    if skipped:
        print(f"Too far from their region, skipped: {', '.join(skipped)}")
    if failed:
        print(f"No result: {', '.join(failed)}")


if __name__ == "__main__":
    main()
