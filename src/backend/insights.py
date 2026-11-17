"""Everything the landing-page map draws, in one payload, shaped per zoom level.

Each level answers a different question, so each gets different figures:
  region   how big is this market and which way is it moving
  zone     which part of the city is hot: price, launches, how fast flats sell
  pincode  what is being built here: sizes, prices, builders, unsold stock
  project  can I trust this one: schedule, progress, complaints, court cases

Quarterly trends need snapshots older than the data we hold, so for now the
eight-quarter series are SAMPLE data: a deterministic walk that ends at the real
current figure. Every trend carries `"sample": true` until real history replaces it.
"""
import hashlib
import random
import time
from datetime import date

import metrics as m

QUARTERS = 8

# RERA files each flat's carpet area but not its type, so BHK is estimated from size with the
# carpet-area ranges usual in Pune and Mumbai. Flats with no area filed are left out.
BHK_CASE = """CASE WHEN u.carpet_area_sqft < 550 THEN '1' WHEN u.carpet_area_sqft < 850 THEN '2'
                   WHEN u.carpet_area_sqft < 1250 THEN '3' ELSE '4' END"""
BHK_KEYS = ("1", "2", "3", "4")


def bhk_rows(con, by: str, where: str = "", params: tuple = ()) -> dict:
    """{key: {bhk: [flats, unsold, priced flats, sum of their price per sq ft, projects]}} grouped by `by`.
    The price sum and count travel separately so the map can weight any mix of BHKs exactly."""
    out: dict = {}
    for r in con.execute(f"""
            SELECT {by} AS key, {BHK_CASE} AS bhk, count(*) AS flats,
                   count(*) FILTER (WHERE u.status = 'unsold') AS unsold,
                   count(*) FILTER (WHERE u.price_per_sqft > 0) AS priced,
                   coalesce(sum(u.price_per_sqft) FILTER (WHERE u.price_per_sqft > 0), 0) AS ppsf_sum,
                   count(DISTINCT u.project_id) AS projects
            FROM units u JOIN projects p ON p.project_id = u.project_id
            WHERE u.carpet_area_sqft > 0 {where}
            GROUP BY 1, 2""", params):
        out.setdefault(r["key"], {})[r["bhk"]] = [r["flats"], r["unsold"], r["priced"], round(float(r["ppsf_sum"])), r["projects"]]
    return out


def bhk_masks(con) -> dict:
    """{pincode: {mask: projects}}: which mix of BHKs each project offers (bit 0 = 1 BHK ... bit 3 = 4+),
    so the map can count projects for any selection without counting one project twice."""
    out: dict = {}
    for r in con.execute(f"""
            WITH m AS (
                SELECT p.pincode, u.project_id, bit_or(1 << (({BHK_CASE})::int - 1)) AS mask
                FROM units u JOIN projects p ON p.project_id = u.project_id
                WHERE u.carpet_area_sqft > 0 GROUP BY 1, 2)
            SELECT pincode, mask, count(*) AS n FROM m GROUP BY 1, 2"""):
        out.setdefault(r["pincode"], {})[str(r["mask"])] = r["n"]
    return out


def mask_sum(parts: list[dict]) -> dict:
    out: dict = {}
    for part in parts:
        for k, n in (part or {}).items():
            out[k] = out.get(k, 0) + n
    return out


def bhk_sum(parts: list[dict]) -> dict:
    """Add pincode BHK figures up to a zone or region (a project spanning sizes counts once per size)."""
    out: dict = {}
    for part in parts:
        for k, row in (part or {}).items():
            acc = out.setdefault(k, [0, 0, 0, 0, 0])
            for i, v in enumerate(row):
                acc[i] += v
    return out


def quarter_labels(today: date | None = None) -> list[str]:
    today = today or date.today()
    q, y = (today.month - 1) // 3 + 1, today.year
    out = []
    for _ in range(QUARTERS):
        out.append(f"Q{q} '{y % 100:02d}")
        q, y = (q - 1, y) if q > 1 else (4, y - 1)
    return out[::-1]


def sample_trend(key: str, price_now: float | None, projects: int) -> dict:
    """Deterministic sample series for one area: price per sq ft and new launches per quarter."""
    rng = random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:12], 16))
    drift = rng.uniform(0.006, 0.034)  # this area's quarterly growth
    prices = []
    if price_now:
        p = float(price_now)
        for _ in range(QUARTERS):
            prices.append(round(p))
            p = p / (1 + drift + rng.uniform(-0.018, 0.018))
        prices.reverse()
    base = max(projects / QUARTERS, 0.4)
    launches = [max(0, round(base * rng.uniform(0.5, 1.6))) for _ in range(QUARTERS)]
    if projects:
        launches[-1] = max(launches[-1], 1)

    def change(series, back):
        a, b = series[-1], series[-1 - back]
        return round((a - b) * 100 / b, 1) if b else None

    return {
        "sample": True,
        "price_per_sqft": prices or None,
        "launches": launches,
        "price_qoq_pct": change(prices, 1) if prices else None,
        "price_yoy_pct": change(prices, 4) if prices else None,
        "launches_qoq_pct": change(launches, 1),
    }


def headline(x: dict, key: str) -> dict:
    """The figures shared by regions, zones and pincodes."""
    ppsf = (x["price_per_sqft"] or {}).get("avg")
    units = x["units"]
    sched = x["schedule"]
    tracked = sched["on_time"] + sched["late"] + sched["early"]
    return {
        "projects": x["projects"],
        "units_total": units["total"],
        "units_unsold": units["unsold"],
        "absorption_pct": units["sold_pct"],
        "price_per_sqft": ppsf,
        "on_time_pct": round((sched["on_time"] + sched["early"]) * 100 / tracked) if tracked else None,
        "new_this_quarter": x["change"]["qoq"]["new_projects"],
        "trend": sample_trend(key, ppsf["inr"] if ppsf else None, x["projects"]),
    }


def build(con) -> dict:
    rate = m.usd_rate(con)
    regions_m = m.area_metrics(con, "region")
    zones_m = m.area_metrics(con, "zone")
    pins_m = m.area_metrics(con, "pincode")
    empty = m.empty_metrics()

    builders: dict[str, list] = {}
    for r in con.execute("""
            SELECT pincode, developer_name, count(*) AS projects FROM projects
            WHERE developer_name IS NOT NULL AND pincode IS NOT NULL
            GROUP BY pincode, developer_name ORDER BY pincode, count(*) DESC, developer_name"""):
        lst = builders.setdefault(r["pincode"], [])
        if len(lst) < 3:
            lst.append({"name": r["developer_name"], "projects": r["projects"]})

    building = {r["pincode"]: r["n"] for r in con.execute("""
        SELECT pincode, count(*) AS n FROM projects
        WHERE coalesce(schedule_status, '') <> 'completed' GROUP BY pincode""")}

    pin_bhk = bhk_rows(con, "p.pincode")
    pin_mask = bhk_masks(con)

    outline = {r["pincode"]: r["geometry"] for r in con.execute("SELECT pincode, geometry FROM pincode_boundaries")}
    zone_outline = {(r["region_id"], r["zone_id"]): r for r in con.execute(
        "SELECT region_id, zone_id, geometry, source FROM zone_boundaries")}

    pincodes = []
    for r in con.execute("SELECT pincode, region_id, zone_id, areas, latitude, longitude FROM pincodes ORDER BY pincode"):
        x = pins_m.get((r["region_id"], r["zone_id"], r["pincode"]), empty)
        lat = r["latitude"] if r["latitude"] is not None else x["centre"]["latitude"]
        lng = r["longitude"] if r["longitude"] is not None else x["centre"]["longitude"]
        if lat is None:
            continue
        bands = x["size_bands"]
        total = sum(b["units"] for b in bands)
        mix = [{"label": b["label"].replace(" sq ft", ""), "units": b["units"],
                "share": round(b["units"] * 100 / total, 1) if total else 0,
                "price_per_sqft": b["price_per_sqft_avg"]} for b in bands]
        top = max(mix, key=lambda b: b["units"]) if total else None
        pincodes.append({
            "id": r["pincode"], "region_id": r["region_id"], "zone_id": r["zone_id"],
            "name": r["pincode"], "area": (r["areas"] or [None])[0], "latitude": lat, "longitude": lng,
            **headline(x, f"pin:{r['pincode']}"),
            "under_construction": building.get(r["pincode"], 0),
            "size_mix": mix, "top_size": top["label"] if top else None,
            "top_builders": builders.get(r["pincode"], []),
            "bhk": pin_bhk.get(r["pincode"], {}), "bhk_projects": pin_mask.get(r["pincode"], {}),
            "boundary": outline.get(r["pincode"]),  # real postal outline, or null until loaded
        })

    zones = []
    for r in con.execute("SELECT region_id, zone_id, name FROM zones ORDER BY region_id, zone_id"):
        x = zones_m.get((r["region_id"], r["zone_id"]), empty)
        own = [p for p in pincodes if p["region_id"] == r["region_id"] and p["zone_id"] == r["zone_id"]]
        if not own:
            continue
        hot = sorted((p for p in own if p["projects"]), key=lambda p: (-p["trend"]["launches"][-1], -p["projects"]))[:3]
        zones.append({
            "id": f"{r['region_id']}/{r['zone_id']}", "region_id": r["region_id"], "zone_id": r["zone_id"],
            "name": r["name"],
            "latitude": x["centre"]["latitude"] or sum(p["latitude"] for p in own) / len(own),
            "longitude": x["centre"]["longitude"] or sum(p["longitude"] for p in own) / len(own),
            **headline(x, f"zone:{r['region_id']}/{r['zone_id']}"),
            "hot_pincodes": [{"pincode": p["id"], "area": p["area"], "launches": p["trend"]["launches"][-1],
                              "price_per_sqft": p["price_per_sqft"]} for p in hot],
            "boundary": (zone_outline.get((r["region_id"], r["zone_id"])) or {}).get("geometry"),
            "boundary_estimated": (zone_outline.get((r["region_id"], r["zone_id"])) or {}).get("source") == "estimated",
            "bhk": bhk_sum([p["bhk"] for p in own]), "bhk_projects": mask_sum([p["bhk_projects"] for p in own]),
        })

    regions = []
    for r in con.execute("SELECT region_id, name, state, extra FROM regions ORDER BY region_id"):
        x = regions_m.get((r["region_id"],), empty)
        fixed = (r["extra"] or {}).get("centre") or {}
        own = [z for z in zones if z["region_id"] == r["region_id"]]
        priced = sorted((z for z in own if z["price_per_sqft"]), key=lambda z: -z["price_per_sqft"]["inr"])
        regions.append({
            "id": r["region_id"], "name": r["name"], "state": r["state"],
            "latitude": x["centre"]["latitude"] or fixed.get("latitude"),
            "longitude": x["centre"]["longitude"] or fixed.get("longitude"),
            **headline(x, f"region:{r['region_id']}"),
            "zones_by_price": [{"name": z["name"], "price_per_sqft": z["price_per_sqft"],
                                "qoq_pct": z["trend"]["price_qoq_pct"]} for z in priced],
            "bhk": bhk_sum([z["bhk"] for z in own]), "bhk_projects": mask_sum([z["bhk_projects"] for z in own]),
        })

    totals = con.execute("""
        SELECT (SELECT count(*) FROM projects)                              AS projects,
               (SELECT count(*) FROM units)                                 AS flats,
               (SELECT count(*) FROM units WHERE price_inr > 0)             AS flats_priced,
               (SELECT coalesce(sum(price_inr), 0) FROM units WHERE price_inr > 0) AS agreed_inr,
               (SELECT count(DISTINCT developer_name) FROM projects)        AS builders,
               (SELECT count(*) FROM pincodes)                              AS pincodes""").fetchone()
    totals["agreed_inr"] = float(totals["agreed_inr"])

    return {"quarters": quarter_labels(), "sample_trends": True, "totals": totals, "inr_per_usd": rate,
            "bhk_ranges": {"1": [0, 550], "2": [550, 850], "3": [850, 1250], "4": [1250, None]},
            "regions": regions, "zones": zones, "pincodes": pincodes}


# The summary above reads every apartment row three times; with the full registry loaded that takes
# seconds, and it only changes when a run is collected. So it is kept for a few minutes.
CACHE_SECONDS = 600
_cache: dict = {}


def cached(con) -> dict:
    hit = _cache.get("build")
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = build(con)
    _cache["build"] = (time.monotonic(), value)
    return value


PROJECT_SQL = """
    SELECT p.rera_id, p.project_name, p.developer_name, p.pincode, p.locality, p.latitude, p.longitude,
           p.schedule_status, p.work_done_percent, p.total_units, p.sold_units, p.booked_units,
           p.price_per_sqft, p.complaint_count, p.pending_litigation_count, p.revised_completion_date,
           p.project_id, p.rera_authority, p.source_url
    FROM projects p JOIN pincodes pc ON pc.pincode = p.pincode
    WHERE p.latitude BETWEEN %s AND %s AND p.longitude BETWEEN %s AND %s
    ORDER BY p.total_units DESC NULLS LAST
    LIMIT %s"""


def projects_in(con, south: float, west: float, north: float, east: float, limit: int = 1500) -> dict:
    """The projects inside a map view, biggest first; the map asks for these only when zoomed in."""
    rate = m.usd_rate(con)
    rows = con.execute(PROJECT_SQL, (south, north, west, east, limit + 1)).fetchall()
    ids = [r["project_id"] for r in rows[:limit]]
    sizes = bhk_rows(con, "u.project_id", "AND u.project_id = ANY(%s)", (ids,)) if ids else {}
    out = [{
        "id": r["rera_id"], "name": r["project_name"] or r["rera_id"], "builder": r["developer_name"],
        "pincode": r["pincode"], "locality": r["locality"],
        "latitude": r["latitude"], "longitude": r["longitude"],
        "schedule": r["schedule_status"],
        "built_pct": float(r["work_done_percent"]) if r["work_done_percent"] is not None else None,
        "units_total": r["total_units"],
        "units_sold": (r["sold_units"] or 0) + (r["booked_units"] or 0) if r["sold_units"] is not None else None,
        "price_per_sqft": m.money(r["price_per_sqft"], rate) if r["price_per_sqft"] else None,
        "complaints": r["complaint_count"], "court_cases": r["pending_litigation_count"],
        "possession": r["revised_completion_date"].isoformat() if r["revised_completion_date"] else None,
        "authority": r["rera_authority"], "url": r["source_url"],
        "bhk": sizes.get(r["project_id"], {}),
    } for r in rows[:limit]]
    return {"projects": out, "truncated": len(rows) > limit}


def points(con, limit: int = 6000, named: int = 150) -> dict:
    """A light sample of project positions for the landing-page backdrop: [lat, lng, late] triples,
    plus a few names to show beside the pulses."""
    rows = con.execute("""
        SELECT round(p.latitude::numeric, 4)::float AS lat, round(p.longitude::numeric, 4)::float AS lng,
               (p.schedule_status IN ('late', 'overdue'))::int AS late, p.project_name, p.pincode
        FROM projects p JOIN pincodes pc ON pc.pincode = p.pincode
        WHERE p.latitude IS NOT NULL AND p.longitude IS NOT NULL
        ORDER BY md5(p.rera_id) LIMIT %s""", (limit,)).fetchall()
    return {"points": [[r["lat"], r["lng"], r["late"]] for r in rows],
            "named": [{"name": r["project_name"], "pincode": r["pincode"], "lat": r["lat"], "lng": r["lng"]}
                      for r in rows[:named] if r["project_name"]]}
