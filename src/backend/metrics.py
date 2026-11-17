"""The numbers behind the map: one metrics block per region, zone or pincode.

All three levels run the same three queries, grouped by a different key:
  1. project totals (counts, units, schedule, legal) from `projects`
  2. size bands and prices from `units`
  3. sold-unit change against past `project_snapshots`
"""
BANDS = [
    ("lt_500", "Below 500 sq ft"),
    ("500_1000", "500 - 1000 sq ft"),
    ("1000_1500", "1000 - 1500 sq ft"),
    ("1500_2000", "1500 - 2000 sq ft"),
    ("2000_2500", "2000 - 2500 sq ft"),
    ("2500_3000", "2500 - 3000 sq ft"),
    ("gte_3000", "3000 sq ft and above"),
]
PERIODS = {"mom": "1 month", "qoq": "3 months", "yoy": "1 year"}
KEYS = {
    "region": ["pc.region_id"],
    "zone": ["pc.region_id", "pc.zone_id"],
    "pincode": ["pc.region_id", "pc.zone_id", "pc.pincode"],
}


def usd_rate(con) -> float:
    row = con.execute("SELECT inr_per_unit FROM fx_rates WHERE currency='USD'").fetchone()
    return float(row["inr_per_unit"]) if row else 88.0


def money(v, rate: float):
    """A rupee amount with its dollar equivalent, or None."""
    if v is None:
        return None
    v = float(v)
    return {"inr": round(v, 2), "usd": round(v / rate, 2)}


def pct_change(now, then):
    if now is None or then in (None, 0):
        return None
    return round((float(now) - float(then)) * 100 / float(then), 2)


def band_rows(rows: list[dict], rate: float) -> list[dict]:
    """Seven fixed bands, in order, zero-filled, from grouped unit rows."""
    by = {r["size_band"]: r for r in rows}
    out = []
    for band, label in BANDS:
        r = by.get(band) or {}
        out.append({
            "band": band, "label": label,
            "units": r.get("units", 0), "sold": r.get("sold", 0),
            "booked": r.get("booked", 0), "unsold": r.get("unsold", 0),
            "price_min": money(r.get("price_min"), rate),
            "price_avg": money(r.get("price_avg"), rate),
            "price_max": money(r.get("price_max"), rate),
            "price_per_sqft_avg": money(r.get("ppsf_avg"), rate),
        })
    return out


def price_per_sqft(rows: list[dict], rate: float, declared_avg=None) -> dict:
    """Lowest / average / highest sold price per sq ft across all bands. Falls back to the
    average the registry declares per project when no apartment-level prices are loaded."""
    priced = [r for r in rows if r.get("priced")]
    if priced:
        n = sum(r["priced"] for r in priced)
        return {
            "min": money(min(r["ppsf_min"] for r in priced), rate),
            "avg": money(sum(float(r["ppsf_avg"]) * r["priced"] for r in priced) / n, rate),
            "max": money(max(r["ppsf_max"] for r in priced), rate),
            "priced_units": n, "basis": "apartments",
        }
    return {"min": None, "avg": money(declared_avg, rate), "max": None, "priced_units": 0,
            "basis": "declared" if declared_avg is not None else None}


UNIT_AGG = """
    count(*)                                                   AS units,
    count(*) FILTER (WHERE u.status = 'sold')                  AS sold,
    count(*) FILTER (WHERE u.status = 'booked')                AS booked,
    count(*) FILTER (WHERE u.status = 'unsold')                AS unsold,
    min(u.price_inr) FILTER (WHERE u.price_inr > 0)            AS price_min,
    avg(u.price_inr) FILTER (WHERE u.price_inr > 0)            AS price_avg,
    max(u.price_inr) FILTER (WHERE u.price_inr > 0)            AS price_max,
    count(*) FILTER (WHERE u.price_per_sqft > 0)               AS priced,
    min(u.price_per_sqft) FILTER (WHERE u.price_per_sqft > 0)  AS ppsf_min,
    avg(u.price_per_sqft) FILTER (WHERE u.price_per_sqft > 0)  AS ppsf_avg,
    max(u.price_per_sqft) FILTER (WHERE u.price_per_sqft > 0)  AS ppsf_max"""


def area_metrics(con, level: str, region_id=None, zone_id=None, pincode=None, cond: str = "") -> dict:
    """Metrics for every area at `level` inside the given filter, keyed by the area's id tuple.
    `cond` is an extra SQL condition on projects `p` (see insights.project_filter)."""
    keys = KEYS[level]
    cols = ", ".join(keys)
    where, params = ["true"], []
    for col, val in (("pc.region_id", region_id), ("pc.zone_id", zone_id), ("pc.pincode", pincode)):
        if val is not None:
            where.append(f"{col} = %s")
            params.append(val)
    where = " AND ".join(where) + cond
    scope = f"FROM projects p JOIN pincodes pc ON pc.pincode = p.pincode WHERE {where}"
    rate = usd_rate(con)
    key_of = lambda r: tuple(r[k.split(".")[1]] for k in keys)  # noqa: E731

    then_cols = ", ".join(
        f"count(*) FILTER (WHERE p.registration_date IS NULL OR p.registration_date <= current_date - interval '{iv}') AS then_{name}, "
        f"count(*) FILTER (WHERE p.registration_date > current_date - interval '{iv}') AS new_{name}"
        for name, iv in PERIODS.items())
    totals = con.execute(f"""
        SELECT {cols}, count(*) AS projects, {then_cols},
               coalesce(sum(p.total_units), 0)  AS total_units,
               coalesce(sum(p.sold_units), 0)   AS sold_units,
               coalesce(sum(p.booked_units), 0) AS booked_units,
               coalesce(sum(p.unsold_units), 0) AS unsold_units,
               count(*) FILTER (WHERE p.detail_level = 'details')               AS projects_with_details,
               count(*) FILTER (WHERE p.has_unit_data)                          AS projects_with_unit_data,
               count(*) FILTER (WHERE p.schedule_status = 'on_time')            AS on_time,
               count(*) FILTER (WHERE p.schedule_status IN ('late', 'overdue')) AS late,
               count(*) FILTER (WHERE p.schedule_status = 'early')              AS early,
               count(*) FILTER (WHERE p.schedule_status = 'completed')          AS completed,
               coalesce(sum(p.complaint_count), 0)          AS complaints,
               coalesce(sum(p.pending_litigation_count), 0) AS pending_court_cases,
               avg(p.price_per_sqft) FILTER (WHERE p.price_per_sqft > 0) AS declared_ppsf,
               -- median, not mean: a few filings carry wrong coordinates and would drag the centre away
               percentile_cont(0.5) WITHIN GROUP (ORDER BY p.latitude)  AS latitude,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY p.longitude) AS longitude
        {scope} GROUP BY {cols}""", params).fetchall()

    bands: dict[tuple, list] = {}
    for r in con.execute(f"""
            SELECT {cols}, u.size_band, {UNIT_AGG}
            FROM units u JOIN projects p USING (project_id) JOIN pincodes pc ON pc.pincode = p.pincode
            WHERE {where} GROUP BY {cols}, u.size_band""", params):
        bands.setdefault(key_of(r), []).append(r)

    sold_then: dict[str, dict] = {}
    for name, iv in PERIODS.items():
        sold_then[name] = {key_of(r): r for r in con.execute(f"""
            SELECT {cols}, sum(p.sold_units) AS now_sold, sum(s.sold_units) AS then_sold, count(*) AS projects
            FROM projects p JOIN pincodes pc ON pc.pincode = p.pincode
            JOIN LATERAL (SELECT sold_units FROM project_snapshots s
                          WHERE s.project_id = p.project_id AND s.sold_units IS NOT NULL
                            AND s.snapshot_date <= current_date - interval '{iv}'
                          ORDER BY s.snapshot_date DESC LIMIT 1) s ON true
            WHERE {where} AND p.sold_units IS NOT NULL GROUP BY {cols}""", params)}

    out = {}
    for t in totals:
        k = key_of(t)
        change = {}
        for name in PERIODS:
            s = sold_then[name].get(k)
            change[name] = {
                "projects_then": t[f"then_{name}"],
                "new_projects": t[f"new_{name}"],
                "projects_change_pct": pct_change(t["projects"], t[f"then_{name}"]),
                # Sold-unit change needs a snapshot at least this old; null until history builds up.
                "sold_units_then": s["then_sold"] if s else None,
                "sold_units_change_pct": pct_change(s["now_sold"], s["then_sold"]) if s else None,
                "projects_with_history": s["projects"] if s else 0,
            }
        total, sold, booked = t["total_units"], t["sold_units"], t["booked_units"]
        out[k] = {
            "projects": t["projects"],
            "change": change,
            "units": {
                "total": total, "sold": sold, "booked": booked, "unsold": t["unsold_units"],
                "sold_pct": round((sold + booked) * 100 / total, 2) if total else None,
            },
            "size_bands": band_rows(bands.get(k, []), rate),
            "price_per_sqft": price_per_sqft(bands.get(k, []), rate, t["declared_ppsf"]),
            "schedule": {"on_time": t["on_time"], "late": t["late"], "early": t["early"], "completed": t["completed"]},
            "legal": {"complaints": t["complaints"], "pending_court_cases": t["pending_court_cases"]},
            "coverage": {"projects_with_details": t["projects_with_details"],
                         "projects_with_unit_data": t["projects_with_unit_data"]},
            "centre": {"latitude": t["latitude"], "longitude": t["longitude"]},
        }
    return out


def empty_metrics() -> dict:
    """What an area with no projects loaded yet looks like."""
    change = {n: {"projects_then": 0, "new_projects": 0, "projects_change_pct": None, "sold_units_then": None,
                  "sold_units_change_pct": None, "projects_with_history": 0} for n in PERIODS}
    return {
        "projects": 0, "change": change,
        "units": {"total": 0, "sold": 0, "booked": 0, "unsold": 0, "sold_pct": None},
        "size_bands": band_rows([], 1.0),
        "price_per_sqft": {"min": None, "avg": None, "max": None, "priced_units": 0, "basis": None},
        "schedule": {"on_time": 0, "late": 0, "early": 0, "completed": 0},
        "legal": {"complaints": 0, "pending_court_cases": 0},
        "coverage": {"projects_with_details": 0, "projects_with_unit_data": 0},
        "centre": {"latitude": None, "longitude": None},
    }


def project_bands(con, project_id: int) -> tuple[list[dict], dict]:
    """Size bands and price per sq ft for one project."""
    rate = usd_rate(con)
    rows = con.execute(f"SELECT u.size_band, {UNIT_AGG} FROM units u WHERE u.project_id = %s GROUP BY u.size_band",
                       (project_id,)).fetchall()
    return band_rows(rows, rate), price_per_sqft(rows, rate)
