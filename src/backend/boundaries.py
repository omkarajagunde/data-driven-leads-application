"""Load real pincode outlines from India Post's boundary GeoJSON and merge them into zone outlines.

    python src/backend/boundaries.py                      # every .geojson / .json in data/raw/boundaries/
    python src/backend/boundaries.py path/to/file.geojson
    python src/backend/boundaries.py --estimate           # zone shapes from pincode centres, until the file arrives
    python src/backend/boundaries.py --clear              # forget all loaded outlines

Only the pincodes in config/regions.json are kept. Each outline is simplified to about 40 m,
which keeps the whole map payload small. The file is read as a stream, so the all-India file
does not need to fit in memory.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import ijson
from shapely import make_valid, voronoi_polygons
from shapely.geometry import MultiPoint, Point, mapping, shape
from shapely.ops import unary_union
from psycopg.types.json import Jsonb

import db

FOLDER = db.ROOT / "data" / "raw" / "boundaries"
SIMPLIFY = 0.0004   # degrees, about 40 m
ZONE_SMOOTH = 0.0006  # closes hairline gaps between neighbouring pincodes when they are merged
PIN_KEYS = ("pincode", "pin_code", "pin", "postal_code", "postcode", "pc", "pincode_no")


def pincode_of(props: dict) -> str | None:
    """Find the 6-digit pincode in a feature's properties, whatever the column is called."""
    lower = {str(k).lower(): v for k, v in props.items()}
    for key in PIN_KEYS:
        v = lower.get(key)
        if v is not None and re.fullmatch(r"\d{6}", str(v).strip().split(".")[0]):
            return str(v).strip().split(".")[0]
    for v in props.values():  # unknown column name: any value that is exactly six digits
        if re.fullmatch(r"\d{6}", str(v).strip()):
            return str(v).strip()
    return None


def clean(geom):
    geom = make_valid(geom)
    if geom.geom_type == "GeometryCollection":
        geom = unary_union([g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")])
    return geom.simplify(SIMPLIFY, preserve_topology=True)


def rounded(geom) -> dict:
    """GeoJSON with coordinates cut to 5 decimals (about 1 m)."""
    def r(c):
        return [r(x) for x in c] if isinstance(c[0], (list, tuple)) else [round(c[0], 5), round(c[1], 5)]
    g = mapping(geom)
    return {"type": g["type"], "coordinates": r(g["coordinates"])}


def read(path: Path, wanted: set[str]) -> tuple[dict[str, list], int]:
    """Outlines for the wanted pincodes from one file, and how many features the file had."""
    found: dict[str, list] = {}
    seen = 0
    with path.open("rb") as f:
        for feat in ijson.items(f, "features.item", use_float=True):
            seen += 1
            pin = pincode_of(feat.get("properties") or {})
            if pin not in wanted or not feat.get("geometry"):
                continue
            x, y = first_point(feat["geometry"]["coordinates"])
            if abs(x) > 180 or abs(y) > 90:
                sys.exit(f"{path.name}: coordinates are not longitude/latitude (WGS84). Reproject the file first.")
            found.setdefault(pin, []).append(shape(feat["geometry"]))
    return found, seen


def first_point(c):
    while isinstance(c[0], (list, tuple)):
        c = c[0]
    return c


ESTIMATE_REACH = 0.055  # degrees, about 6 km: how far an estimated pincode area reaches past its centre


def estimate(con) -> None:
    """Zone shapes without outline data: every pincode takes the land nearer to it than to any other
    pincode (a Voronoi split over all regions at once, so neighbouring regions never overlap), capped
    at about 6 km, and each zone is the merge of its pincodes' pieces. Approximate by design; loading
    a real outline file replaces them."""
    if con.execute("SELECT 1 FROM zone_boundaries WHERE source = 'outlines' LIMIT 1").fetchone():
        print("Real outlines are loaded; estimated zone shapes are not needed.")
        return
    rows = [r for r in con.execute("""
        SELECT pc.pincode, pc.region_id, pc.zone_id,
               coalesce(pc.latitude,  percentile_cont(0.5) WITHIN GROUP (ORDER BY p.latitude))  AS lat,
               coalesce(pc.longitude, percentile_cont(0.5) WITHIN GROUP (ORDER BY p.longitude)) AS lng
        FROM pincodes pc LEFT JOIN projects p ON p.pincode = pc.pincode AND p.latitude IS NOT NULL
        GROUP BY pc.pincode""") if r["lat"] is not None]
    points = MultiPoint([(r["lng"], r["lat"]) for r in rows])
    cells = list(voronoi_polygons(points, extend_to=points.envelope.buffer(1)).geoms)
    zones: dict[tuple, list] = {}
    for r in rows:
        pt = Point(r["lng"], r["lat"])
        cell = next((c for c in cells if c.covers(pt)), None)
        if cell is not None:
            zones.setdefault((r["region_id"], r["zone_id"]), []).append(cell.intersection(pt.buffer(ESTIMATE_REACH)))
    con.execute("DELETE FROM zone_boundaries WHERE source = 'estimated'")
    for (region_id, zone_id), parts in zones.items():
        merged = clean(unary_union(parts).buffer(ZONE_SMOOTH * 3).buffer(-ZONE_SMOOTH * 3))
        con.execute("""
            INSERT INTO zone_boundaries (region_id, zone_id, geometry, source) VALUES (%s, %s, %s, 'estimated')
            ON CONFLICT (region_id, zone_id) DO NOTHING""", (region_id, zone_id, Jsonb(rounded(merged))))
    con.commit()
    print(f"Estimated shapes for {len(zones)} zones from {len(rows)} pincode centres "
          f"({con.execute('SELECT count(*) AS n FROM pincodes').fetchone()['n'] - len(rows)} pincodes have no position yet).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--clear", action="store_true", help="delete all loaded outlines and stop")
    ap.add_argument("--estimate", action="store_true", help="estimated zone shapes from pincode centres, then stop")
    args = ap.parse_args()

    con = db.connect()
    db.init_schema(con)
    if args.clear:
        con.execute("DELETE FROM zone_boundaries")
        con.execute("DELETE FROM pincode_boundaries")
        con.commit()
        print("Cleared all pincode and zone outlines.")
        return
    if args.estimate:
        estimate(con)
        return

    files = args.files or sorted(p for p in FOLDER.glob("*") if p.suffix.lower() in (".geojson", ".json"))
    if not files:
        sys.exit(f"No boundary file given and none found in {FOLDER.relative_to(db.ROOT)}/")

    pins = {r["pincode"]: r for r in con.execute("SELECT pincode, region_id, zone_id FROM pincodes")}
    shapes: dict[str, list] = {}
    source: dict[str, str] = {}
    for path in files:
        found, seen = read(path, set(pins))
        print(f"{path.name}: {seen:,} features, {len(found)} of our pincodes")
        for pin, parts in found.items():
            shapes.setdefault(pin, []).extend(parts)
            source[pin] = path.name

    outlines = {}
    for pin, parts in shapes.items():
        geom = clean(unary_union([make_valid(p) for p in parts]))
        if not geom.is_empty:
            outlines[pin] = geom
            con.execute("""
                INSERT INTO pincode_boundaries (pincode, geometry, source) VALUES (%s, %s, %s)
                ON CONFLICT (pincode) DO UPDATE SET geometry = EXCLUDED.geometry, source = EXCLUDED.source,
                                                    loaded_at = now()""",
                        (pin, Jsonb(rounded(geom)), source[pin]))

    # Zones are rebuilt from every outline in the table, so loading a second file adds to the first.
    # Real outlines replace every estimated zone shape, so the two never overlap on the map.
    con.execute("DELETE FROM zone_boundaries WHERE source = 'estimated'")
    stored = {r["pincode"]: shape(r["geometry"]) for r in con.execute("SELECT pincode, geometry FROM pincode_boundaries")}
    zones: dict[tuple, list] = {}
    for pin, geom in stored.items():
        p = pins[pin]
        zones.setdefault((p["region_id"], p["zone_id"]), []).append(geom)
    for (region_id, zone_id), parts in zones.items():
        merged = unary_union(parts).buffer(ZONE_SMOOTH).buffer(-ZONE_SMOOTH)
        merged = clean(merged)
        con.execute("""
            INSERT INTO zone_boundaries (region_id, zone_id, geometry, source) VALUES (%s, %s, %s, 'outlines')
            ON CONFLICT (region_id, zone_id) DO UPDATE SET geometry = EXCLUDED.geometry, source = 'outlines',
                                                          loaded_at = now()""",
                    (region_id, zone_id, Jsonb(rounded(merged))))
    con.commit()

    missing = sorted(set(pins) - set(stored))
    print(f"Outlines stored: {len(stored)} of {len(pins)} pincodes, {len(zones)} zones.")
    if missing:
        print(f"No outline for {len(missing)} pincodes (they keep a hexagon): {', '.join(missing[:30])}"
              + (" ..." if len(missing) > 30 else ""))


if __name__ == "__main__":
    main()
