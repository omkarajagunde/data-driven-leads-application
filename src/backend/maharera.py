"""Turn one item from the nice_dev/maharera-projects-scraper actor into our rows and store it.

Main keys become columns on `projects`; the per-apartment lists become `units` rows; everything
else from the item is kept as-is in projects.details (jsonb).
"""
from datetime import date, datetime, timezone

from psycopg.types.json import Jsonb

AUTHORITY = "MahaRERA"
SQM_TO_SQFT = 10.7639
UNIT_LISTS = (("soldUnits", "sold"), ("bookedUnits", "booked"), ("unsoldUnits", "unsold"))
# Litigation statuses that mean the case is over; anything else counts as pending.
CLOSED_WORDS = ("closed", "disposed", "dismissed", "withdrawn", "settled", "decided")

# Columns written on every load. A later, thinner load (registry row only) never blanks out
# what a fuller load already stored: see the COALESCE in upsert_project.
COLUMNS = [
    "project_name", "developer_name", "developer_id", "property_type", "project_status",
    "registration_status", "state", "district", "taluka", "locality", "address", "pincode",
    "latitude", "longitude", "application_date", "registration_date", "certificate_date",
    "original_completion_date", "revised_completion_date", "completion_delay_days", "schedule_status",
    "total_units", "sold_units", "booked_units", "unsold_units", "work_done_percent", "total_cost",
    "price_min", "price_max", "price_per_sqft", "complaint_count", "litigation_count",
    "pending_litigation_count", "source_url",
]
UNIT_COUNT_COLUMNS = ("sold_units", "booked_units", "unsold_units")
SNAPSHOT_COLUMNS = [
    "registration_status", "revised_completion_date", "completion_delay_days", "total_units",
    "sold_units", "booked_units", "unsold_units", "work_done_percent", "price_per_sqft",
    "complaint_count", "litigation_count",
]


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(v):
    f = _num(v)
    return int(f) if f is not None else None


def _date(v):
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def has_units(item: dict) -> bool:
    return any(isinstance(item.get(k), list) for k, _ in UNIT_LISTS)


def has_details(item: dict) -> bool:
    return isinstance(item.get("buildings"), list) or isinstance(item.get("financing"), dict)


def schedule_status(item: dict, today: date | None = None) -> str | None:
    """on_time | late | overdue | early | completed.
    late    = the developer pushed the completion date back (the actor already ignores the
              blanket extension MahaRERA gave every project).
    overdue = the promised date has passed and the project is not marked completed."""
    today = today or date.today()
    original, revised = _date(item.get("originalCompletionDate")), _date(item.get("revisedCompletionDate"))
    target = revised or original
    if "complet" in (item.get("registrationStatus") or "").lower():
        return "completed"
    if target and target < today:
        return "overdue"
    if (_int(item.get("completionDelayDays")) or 0) > 0:
        return "late"
    if original and revised and revised < original:
        return "early"
    return "on_time" if target else None


def normalise(item: dict) -> dict:
    g = item.get
    total = _int(g("totalUnits"))
    if has_units(item):
        sold, booked, unsold = (len(g(k) or []) for k, _ in UNIT_LISTS)
    else:
        sold, booked = _int(g("soldUnitsCount")), None
        unsold = total - sold if total is not None and sold is not None else None
    litigations = g("litigations") if isinstance(g("litigations"), list) else None
    pending = None
    if litigations is not None:
        pending = sum(1 for c in litigations
                      if not any(w in (c.get("status") or "").lower() for w in CLOSED_WORDS))
    return {
        "rera_id": g("reraId") or g("registrationNumber"),
        "project_name": g("projectName"),
        "developer_name": g("developer"),
        "developer_id": str(g("developerId")) if g("developerId") is not None else None,
        "property_type": g("propertyType"),
        "project_status": g("projectStatus"),
        "registration_status": g("registrationStatus"),
        "state": g("state"),
        "district": g("district"),
        "taluka": g("taluka"),
        "locality": g("locality") or g("village"),
        "address": g("address"),
        "pincode": str(g("pinCode")).strip() if g("pinCode") else None,
        "latitude": _num(g("latitude")),
        "longitude": _num(g("longitude")),
        "application_date": _date(g("applicationDate")),
        "registration_date": _date(g("registrationDate")),
        "certificate_date": _date(g("certificateDate")),
        "original_completion_date": _date(g("originalCompletionDate")),
        "revised_completion_date": _date(g("revisedCompletionDate")) or _date(g("originalCompletionDate")),
        "completion_delay_days": _int(g("completionDelayDays")),
        "schedule_status": schedule_status(item),
        "total_units": total,
        "sold_units": sold,
        "booked_units": booked,
        "unsold_units": unsold,
        "work_done_percent": _num(g("workDonePercent")),
        "total_cost": _num(g("totalCost")),
        "price_min": _num(g("priceMin")),
        "price_max": _num(g("priceMax")),
        "price_per_sqft": _num(g("pricePerSqFt")),
        "complaint_count": _int(g("complaintCount")),
        "litigation_count": _int(g("litigationCount")),
        "pending_litigation_count": pending,
        "source_url": g("url"),
    }


def upsert_project(con, item: dict, source: str = "apify") -> tuple[int, int] | None:
    """Store one item. Returns (project_id, unit rows written) or None when it has no RERA number."""
    rec = normalise(item)
    if not rec["rera_id"]:
        return None
    level = "details" if has_details(item) else "list"
    units = has_units(item)
    details = {k: v for k, v in item.items() if k not in dict(UNIT_LISTS)}
    scraped = item.get("scrapedAt") or datetime.now(timezone.utc).isoformat()

    cols = ", ".join(COLUMNS)
    marks = ", ".join(["%s"] * len(COLUMNS))
    # Unit counts from the apartment lists are more exact than the registry's own sold counter,
    # so a later registry-only load does not replace them.
    keep = ", ".join(
        f"{c}=CASE WHEN projects.has_unit_data AND NOT excluded.has_unit_data THEN projects.{c} "
        f"ELSE COALESCE(excluded.{c}, projects.{c}) END" if c in UNIT_COUNT_COLUMNS
        else f"{c}=COALESCE(excluded.{c}, projects.{c})" for c in COLUMNS)
    row = con.execute(
        f"""INSERT INTO projects(rera_authority, rera_id, {cols}, has_unit_data, detail_level, source, details, last_scraped_at)
            VALUES (%s, %s, {marks}, %s, %s, %s, %s, %s)
            ON CONFLICT (rera_authority, rera_id) DO UPDATE SET {keep},
                has_unit_data = projects.has_unit_data OR excluded.has_unit_data,
                detail_level  = CASE WHEN projects.detail_level='details' THEN 'details' ELSE excluded.detail_level END,
                details       = CASE WHEN projects.detail_level='details' AND excluded.detail_level='list'
                                     THEN projects.details ELSE excluded.details END,
                source = excluded.source, last_scraped_at = excluded.last_scraped_at
            RETURNING project_id, has_unit_data""",
        [AUTHORITY, rec["rera_id"]] + [rec[c] for c in COLUMNS] + [units, level, source, Jsonb(details), scraped],
    ).fetchone()
    pid = row["project_id"]
    if row["has_unit_data"] and not units:
        rec = {**rec, **{c: None for c in UNIT_COUNT_COLUMNS}}

    snap_cols = ", ".join(SNAPSHOT_COLUMNS)
    snap_keep = ", ".join(f"{c}=COALESCE(excluded.{c}, project_snapshots.{c})" for c in SNAPSHOT_COLUMNS)
    con.execute(
        f"""INSERT INTO project_snapshots(project_id, snapshot_date, {snap_cols})
            VALUES (%s, %s, {", ".join(["%s"] * len(SNAPSHOT_COLUMNS))})
            ON CONFLICT (project_id, snapshot_date) DO UPDATE SET {snap_keep}""",
        [pid, _date(scraped) or date.today()] + [rec[c] for c in SNAPSHOT_COLUMNS],
    )
    return pid, (upsert_units(con, pid, item) if units else 0)


def upsert_units(con, project_id: int, item: dict) -> int:
    """Write the apartment rows of one item and drop apartments the developer no longer lists."""
    ts = datetime.now(timezone.utc)
    rows = {}
    for key, status in UNIT_LISTS:
        for u in item.get(key) or []:
            building, unit_no = u.get("building"), u.get("unit")
            if not building or unit_no in (None, ""):
                continue
            sqm = _num(u.get("carpetAreaSqm"))
            sqft = round(sqm * SQM_TO_SQFT, 2) if sqm else None
            price = _num(u.get("agreementPrice"))
            psf = round(price / sqft, 2) if price and sqft else None
            extra = {k: u.get(k) for k in ("carpetAreaSqm", "receivedAmount", "balanceAmount", "reckonerValue")
                     if u.get(k) is not None}
            wing = u.get("wing") or ""
            rows[(building, wing, str(unit_no))] = (
                project_id, building, wing, str(unit_no), u.get("floor"), status, sqft, price, psf, Jsonb(extra), ts)
    if rows:
        with con.cursor() as cur:
            cur.executemany(
                """INSERT INTO units(project_id, building, wing, unit_no, floor, status, carpet_area_sqft,
                       price_inr, price_per_sqft, extra, last_seen_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (project_id, building, wing, unit_no) DO UPDATE SET
                       floor=excluded.floor, carpet_area_sqft=excluded.carpet_area_sqft,
                       price_inr=excluded.price_inr, price_per_sqft=excluded.price_per_sqft,
                       extra=excluded.extra, last_seen_at=excluded.last_seen_at,
                       status_changed_at=CASE WHEN units.status=excluded.status
                                              THEN units.status_changed_at ELSE excluded.last_seen_at END,
                       status=excluded.status""",
                list(rows.values()),
            )
    con.execute("DELETE FROM units WHERE project_id=%s AND last_seen_at<%s", (project_id, ts))
    return len(rows)
