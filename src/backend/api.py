#!/usr/bin/env python3
"""FastAPI server over the leads database.

  .venv/bin/uvicorn api:app --app-dir src/backend --reload --port 8000
  Swagger UI: http://localhost:8000/docs      (click Authorize and paste an API key)

The endpoints follow the map zoom: regions -> zones -> pincodes -> projects -> one project.
Every area carries the same `metrics` block, so the front end can reuse one component.
"""
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402
import env  # noqa: E402
import insights  # noqa: E402
from ratelimit import RateLimit  # noqa: E402
import metrics as m  # noqa: E402

env.load_dotenv()
FRONTEND_DIST = db.ROOT / "src" / "frontend" / "dist"

DESCRIPTION = """
RERA project data rolled up for a zoomable map.

**Zoom levels**

1. `GET /v1/regions` — every region with its metrics
2. `GET /v1/regions/{region_id}/zones` — the zones of one region
3. `GET /v1/regions/{region_id}/zones/{zone_id}/pincodes` — the pincodes of one zone
4. `GET /v1/pincodes/{pincode}` — one pincode with its project list
5. `GET /v1/projects/{rera_id}` — full analysis of one project

**The `metrics` block** (same shape at every level)

- `projects`, and `change.mom / qoq / yoy`: project counts compared with one month, one quarter and
  one year ago (by registration date), plus sold-unit change once snapshots that old exist
- `units`: total, sold, booked, unsold
- `size_bands`: seven carpet-area bands with unit counts and lowest / average / highest price
- `price_per_sqft`: lowest / average / highest, in rupees and dollars
- `schedule`, `legal`, `coverage`, `centre`

Money values are objects: `{"inr": 12040.0, "usd": 136.82}`.

Send your key in the `X-API-Key` header.
"""

app = FastAPI(title="Subak API", version="1.0.0", description=DESCRIPTION)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class FrontendApi:
    """The built landing page calls /api/... on this same server. Those calls are passed on to the
    real routes with FRONTEND_API_KEY added, so the key stays on the server and never ships to
    the browser. (The Vite dev server does the same job during development.)"""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/api/"):
            path = scope["path"][len("/api"):]
            headers = list(scope["headers"])
            key = os.environ.get("FRONTEND_API_KEY")
            if key and not any(name == b"x-api-key" for name, _ in headers):
                headers.append((b"x-api-key", key.encode()))
            scope = {**scope, "path": path, "raw_path": path.encode(), "headers": headers}
        await self.inner(scope, receive, send)


app.add_middleware(FrontendApi)
app.add_middleware(GZipMiddleware, minimum_size=2048)
# Outermost, so it counts the request as the client sent it (before the page's key is added).
app.add_middleware(RateLimit)


def get_con():
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


def require_key(key: str | None = Security(api_key_header), con=Depends(get_con)) -> str:
    if not key:
        raise HTTPException(401, "Missing X-API-Key header")
    row = con.execute(
        """UPDATE api_keys SET last_used_at = now()
           WHERE key_hash = %s AND revoked_at IS NULL RETURNING label""",
        (hashlib.sha256(key.encode()).hexdigest(),)).fetchone()
    con.commit()
    if not row:
        raise HTTPException(401, "Invalid or revoked API key")
    return row["label"]


# ------------------------------------------------------------------ response models
class Money(BaseModel):
    inr: float
    usd: float


class PeriodChange(BaseModel):
    projects_then: int
    new_projects: int
    projects_change_pct: float | None
    sold_units_then: int | None
    sold_units_change_pct: float | None
    projects_with_history: int


class Change(BaseModel):
    mom: PeriodChange
    qoq: PeriodChange
    yoy: PeriodChange


class Units(BaseModel):
    total: int
    sold: int
    booked: int
    unsold: int
    sold_pct: float | None


class SizeBand(BaseModel):
    band: str
    label: str
    units: int
    sold: int
    booked: int
    unsold: int
    price_min: Money | None
    price_avg: Money | None
    price_max: Money | None
    price_per_sqft_avg: Money | None


class PricePerSqft(BaseModel):
    min: Money | None
    avg: Money | None
    max: Money | None
    priced_units: int
    basis: str | None


class Schedule(BaseModel):
    on_time: int
    late: int
    early: int
    completed: int


class Legal(BaseModel):
    complaints: int
    pending_court_cases: int


class Coverage(BaseModel):
    projects_with_details: int
    projects_with_unit_data: int


class Centre(BaseModel):
    latitude: float | None
    longitude: float | None


class Metrics(BaseModel):
    projects: int
    change: Change
    units: Units
    size_bands: list[SizeBand]
    price_per_sqft: PricePerSqft
    schedule: Schedule
    legal: Legal
    coverage: Coverage
    centre: Centre


class Rera(BaseModel):
    authority: str | None
    website: str | None


class RegionOut(BaseModel):
    region_id: str
    name: str
    state: str | None
    rera: Rera
    zone_count: int
    pincode_count: int
    metrics: Metrics


class ZoneOut(BaseModel):
    region_id: str
    zone_id: str
    name: str
    pincode_count: int
    metrics: Metrics


class PincodeOut(BaseModel):
    pincode: str
    region_id: str
    zone_id: str
    district: str | None
    areas: list[str]
    metrics: Metrics


class ProjectSummary(BaseModel):
    rera_id: str
    rera_authority: str
    project_name: str | None
    developer_name: str | None
    property_type: str | None
    registration_status: str | None
    pincode: str | None
    locality: str | None
    latitude: float | None
    longitude: float | None
    registration_date: Any
    revised_completion_date: Any
    schedule_status: str | None
    total_units: int | None
    sold_units: int | None
    booked_units: int | None
    unsold_units: int | None
    work_done_percent: float | None
    price_per_sqft: Money | None
    complaint_count: int | None
    pending_litigation_count: int | None
    detail_level: str


class PincodeDetail(PincodeOut):
    projects: list[ProjectSummary]


class ProjectPage(BaseModel):
    total: int
    limit: int
    offset: int
    projects: list[ProjectSummary]


SUMMARY_COLS = """p.rera_id, p.rera_authority, p.project_name, p.developer_name, p.property_type,
    p.registration_status, p.pincode, p.locality, p.latitude, p.longitude, p.registration_date,
    p.revised_completion_date, p.schedule_status, p.total_units, p.sold_units, p.booked_units,
    p.unsold_units, p.work_done_percent, p.price_per_sqft, p.complaint_count,
    p.pending_litigation_count, p.detail_level"""


def summary(row: dict, rate: float) -> dict:
    return {**row, "price_per_sqft": m.money(row["price_per_sqft"], rate)}


def with_centre(metrics: dict, lat, lng) -> dict:
    """Prefer a fixed centre from the pincodes table over the median of project positions."""
    if lat is not None and lng is not None:
        return {**metrics, "centre": {"latitude": lat, "longitude": lng}}
    return metrics


# ------------------------------------------------------------------ endpoints
@app.get("/health", tags=["meta"], summary="Liveness check (no key needed)")
def health(con=Depends(get_con)):
    row = con.execute("SELECT count(*) AS projects, max(last_scraped_at) AS last_scraped_at FROM projects").fetchone()
    return {"status": "ok", **row}


@app.get("/v1/regions", response_model=list[RegionOut], tags=["map"], summary="Zoom 1: all regions")
def regions(con=Depends(get_con), _=Depends(require_key)):
    met = m.area_metrics(con, "region")
    rows = con.execute(
        """SELECT r.region_id, r.name, r.state, r.rera_authority, r.rera_website, r.extra,
                  (SELECT count(*) FROM zones z WHERE z.region_id = r.region_id) AS zone_count,
                  (SELECT count(*) FROM pincodes pc WHERE pc.region_id = r.region_id) AS pincode_count
           FROM regions r ORDER BY r.name""").fetchall()
    out = []
    for r in rows:
        metrics = met.get((r["region_id"],), m.empty_metrics())
        fixed = (r["extra"] or {}).get("centre") or {}
        if metrics["centre"]["latitude"] is None:  # no projects yet: use the centre from regions.json
            metrics = with_centre(metrics, fixed.get("latitude"), fixed.get("longitude"))
        out.append({**r, "rera": {"authority": r["rera_authority"], "website": r["rera_website"]}, "metrics": metrics})
    return out


@app.get("/v1/regions/{region_id}/zones", response_model=list[ZoneOut], tags=["map"],
         summary="Zoom 2: zones of a region")
def zones(region_id: str, con=Depends(get_con), _=Depends(require_key)):
    rows = con.execute(
        """SELECT z.region_id, z.zone_id, z.name,
                  (SELECT count(*) FROM pincodes pc WHERE pc.region_id = z.region_id AND pc.zone_id = z.zone_id) AS pincode_count
           FROM zones z WHERE z.region_id = %s ORDER BY z.zone_id""", (region_id,)).fetchall()
    if not rows:
        raise HTTPException(404, f"Unknown region '{region_id}'")
    met = m.area_metrics(con, "zone", region_id=region_id)
    return [{**r, "metrics": met.get((r["region_id"], r["zone_id"]), m.empty_metrics())} for r in rows]


@app.get("/v1/regions/{region_id}/zones/{zone_id}/pincodes", response_model=list[PincodeOut], tags=["map"],
         summary="Zoom 3: pincodes of a zone")
def zone_pincodes(region_id: str, zone_id: str, con=Depends(get_con), _=Depends(require_key)):
    if not con.execute("SELECT 1 FROM zones WHERE region_id = %s AND zone_id = %s", (region_id, zone_id)).fetchone():
        raise HTTPException(404, f"Unknown zone '{region_id}/{zone_id}'")
    rows = con.execute(
        """SELECT pincode, region_id, zone_id, district_name AS district, areas, latitude, longitude
           FROM pincodes WHERE region_id = %s AND zone_id = %s ORDER BY pincode""", (region_id, zone_id)).fetchall()
    met = m.area_metrics(con, "pincode", region_id=region_id, zone_id=zone_id)
    return [{**r, "metrics": with_centre(met.get((region_id, zone_id, r["pincode"]), m.empty_metrics()),
                                         r["latitude"], r["longitude"])} for r in rows]


@app.get("/v1/pincodes/{pincode}", response_model=PincodeDetail, tags=["map"],
         summary="Zoom 4: one pincode and its projects")
def pincode_detail(pincode: str, con=Depends(get_con), _=Depends(require_key)):
    r = con.execute(
        """SELECT pincode, region_id, zone_id, district_name AS district, areas, latitude, longitude
           FROM pincodes WHERE pincode = %s""", (pincode,)).fetchone()
    if not r:
        raise HTTPException(404, f"Pincode '{pincode}' is not in any region")
    met = m.area_metrics(con, "pincode", pincode=pincode)
    rate = m.usd_rate(con)
    projects = con.execute(
        f"SELECT {SUMMARY_COLS} FROM projects p WHERE p.pincode = %s ORDER BY p.total_units DESC NULLS LAST", (pincode,)).fetchall()
    return {**r, "metrics": with_centre(met.get((r["region_id"], r["zone_id"], pincode), m.empty_metrics()),
                                        r["latitude"], r["longitude"]),
            "projects": [summary(p, rate) for p in projects]}


@app.get("/v1/projects", response_model=ProjectPage, tags=["projects"], summary="Search projects")
def projects(
    region_id: str | None = None,
    zone_id: str | None = None,
    pincode: str | None = None,
    q: str | None = Query(None, description="Text in the project or developer name"),
    schedule_status: str | None = Query(None, description="on_time | late | overdue | early | completed"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    con=Depends(get_con), _=Depends(require_key),
):
    where, params = ["true"], []
    for col, val in (("pc.region_id", region_id), ("pc.zone_id", zone_id), ("p.pincode", pincode),
                     ("p.schedule_status", schedule_status)):
        if val is not None:
            where.append(f"{col} = %s")
            params.append(val)
    if q:
        where.append("(p.project_name ILIKE %s OR p.developer_name ILIKE %s)")
        params += [f"%{q}%", f"%{q}%"]
    base = f"FROM projects p LEFT JOIN pincodes pc ON pc.pincode = p.pincode WHERE {' AND '.join(where)}"
    total = con.execute(f"SELECT count(*) AS n {base}", params).fetchone()["n"]
    rows = con.execute(
        f"SELECT {SUMMARY_COLS} {base} ORDER BY p.total_units DESC NULLS LAST, p.rera_id LIMIT %s OFFSET %s",
        params + [limit, offset]).fetchall()
    rate = m.usd_rate(con)
    return {"total": total, "limit": limit, "offset": offset, "projects": [summary(r, rate) for r in rows]}


class MapPincode(BaseModel):
    pincode: str
    region_id: str
    zone_id: str
    areas: list[str]
    latitude: float | None
    longitude: float | None
    projects: int
    units_total: int
    price_per_sqft: Money | None


@app.get("/v1/map/pincodes", response_model=list[MapPincode], tags=["map"],
         summary="Every pincode with its position and headline numbers, for drawing the map")
def map_pincodes(con=Depends(get_con), _=Depends(require_key)):
    met = m.area_metrics(con, "pincode")
    out = []
    for r in con.execute("SELECT pincode, region_id, zone_id, areas, latitude, longitude FROM pincodes ORDER BY pincode"):
        x = met.get((r["region_id"], r["zone_id"], r["pincode"]))
        centre = (x or {}).get("centre") or {}
        out.append({
            "pincode": r["pincode"], "region_id": r["region_id"], "zone_id": r["zone_id"], "areas": r["areas"],
            "latitude": r["latitude"] if r["latitude"] is not None else centre.get("latitude"),
            "longitude": r["longitude"] if r["longitude"] is not None else centre.get("longitude"),
            "projects": x["projects"] if x else 0,
            "units_total": x["units"]["total"] if x else 0,
            "price_per_sqft": x["price_per_sqft"]["avg"] if x else None,
        })
    return out


SINCE = Query(None, ge=2000, le=2100, description="Only projects registered on or after 1 January of this year")
STATUS = Query(None, description="Only projects in any of these states, comma-separated: " + ", ".join(insights.STATUSES))


def statuses(status: str | None) -> tuple:
    picked = tuple(sorted({s.strip() for s in (status or "").split(",") if s.strip()}))
    unknown = [s for s in picked if s not in insights.STATUSES]
    if unknown:
        raise HTTPException(422, f"Unknown status {', '.join(unknown)}; use {', '.join(insights.STATUSES)}.")
    return picked


@app.get("/v1/map/insights", tags=["map"],
         summary="Everything the landing-page map draws: regions, zones, pincodes and projects with level-specific insights")
def map_insights(since: int | None = SINCE, status: str | None = STATUS,
                 con=Depends(get_con), _=Depends(require_key)) -> dict:
    """Quarterly trends in this payload are sample data (`sample: true`) until real snapshot history exists.
    Projects are not in this payload; the map asks `/v1/map/projects` for the ones in view."""
    return insights.cached(con, since, statuses(status))


@app.get("/v1/map/projects", tags=["map"], summary="Projects inside a map view (biggest first)")
def map_projects(south: float = Query(..., ge=-90, le=90), west: float = Query(..., ge=-180, le=180),
                 north: float = Query(..., ge=-90, le=90), east: float = Query(..., ge=-180, le=180),
                 limit: int = Query(1500, ge=1, le=3000), since: int | None = SINCE, status: str | None = STATUS,
                 con=Depends(get_con), _=Depends(require_key)) -> dict:
    if north - south > 1.5 or east - west > 1.5:
        raise HTTPException(422, "Zoom in further: a view may span at most 1.5 degrees.")
    return insights.projects_in(con, south, west, north, east, limit, since, statuses(status))


@app.get("/v1/map/points", tags=["map"], summary="A light sample of project positions for the landing page")
def map_points(con=Depends(get_con), _=Depends(require_key)) -> dict:
    return insights.points(con)


class WaitlistIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    profession: str = Field(min_length=2, max_length=60)
    categories: list[str] = Field(default_factory=list, max_length=20)
    whatsapp: str = Field(min_length=10, max_length=20, description="Indian mobile number, with or without +91")


@app.post("/v1/waitlist", status_code=201, tags=["waitlist"], summary="Join the waitlist")
def join_waitlist(body: WaitlistIn, con=Depends(get_con), _=Depends(require_key)) -> dict:
    """Stores what the person typed into the landing page form. Joining twice with the same
    WhatsApp number updates the earlier entry."""
    digits = re.sub(r"\D", "", body.whatsapp)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        raise HTTPException(422, "Enter a 10-digit Indian mobile number.")
    name = " ".join(body.name.split())
    if len(name) < 2:
        raise HTTPException(422, "Enter your name.")
    categories = [c.strip()[:60] for c in body.categories if c.strip()]
    row = con.execute(
        """INSERT INTO waitlist(name, profession, categories, whatsapp) VALUES (%s, %s, %s, %s)
           ON CONFLICT (whatsapp) DO UPDATE SET name = excluded.name, profession = excluded.profession,
               categories = excluded.categories, updated_at = now()
           RETURNING (xmax = 0) AS inserted""",
        (name, body.profession.strip(), Jsonb(categories), "+91" + digits)).fetchone()
    con.commit()
    return {"status": "joined" if row["inserted"] else "updated"}


def find_project(con, rera_id: str) -> dict:
    row = con.execute("SELECT * FROM projects WHERE upper(rera_id) = upper(%s)", (rera_id.strip(),)).fetchone()
    if not row:
        raise HTTPException(404, f"Project '{rera_id}' not found")
    return row


@app.get("/v1/projects/{rera_id}", tags=["projects"], summary="Zoom 5: full analysis of one project")
def project_detail(rera_id: str, con=Depends(get_con), _=Depends(require_key)) -> dict:
    """Identity, promoter, schedule (on time / late / early), construction progress, sales,
    size bands with price range per band, complaints, court cases, financing and the last filing date.
    Sections that need the full project file are `null` when only the registry row has been loaded
    (`detail_level` = `list`)."""
    p = find_project(con, rera_id)
    d = p["details"] or {}
    rate = m.usd_rate(con)
    bands, ppsf = m.project_bands(con, p["project_id"])
    if not ppsf["priced_units"]:
        ppsf = {**ppsf, "avg": m.money(p["price_per_sqft"], rate), "basis": "declared" if p["price_per_sqft"] else None}
    area = con.execute("SELECT region_id, zone_id, district_name, areas FROM pincodes WHERE pincode = %s",
                       (p["pincode"],)).fetchone()
    total, sold, booked = p["total_units"], p["sold_units"], p["booked_units"]
    litigations = d.get("litigations")
    return {
        "rera_id": p["rera_id"], "rera_authority": p["rera_authority"], "project_name": p["project_name"],
        "property_type": p["property_type"], "project_status": p["project_status"],
        "registration_status": p["registration_status"], "detail_level": p["detail_level"],
        "source_url": p["source_url"], "last_scraped_at": p["last_scraped_at"],
        "location": {
            "address": p["address"], "locality": p["locality"], "taluka": p["taluka"], "district": p["district"],
            "state": p["state"], "pincode": p["pincode"], "latitude": p["latitude"], "longitude": p["longitude"],
            "region_id": area["region_id"] if area else None, "zone_id": area["zone_id"] if area else None,
        },
        "promoter": {
            "name": p["developer_name"], "id": p["developer_id"], "type": d.get("developerType"),
            "address": d.get("developerAddress"), "district": d.get("developerDistrict"),
            "directors": d.get("developerDirectors"), "memberships": d.get("developerMemberships"),
            "other_projects": con.execute(
                "SELECT count(*) AS n FROM projects WHERE developer_id = %s AND project_id <> %s",
                (p["developer_id"], p["project_id"])).fetchone()["n"] if p["developer_id"] else 0,
        },
        "schedule": {
            "status": p["schedule_status"], "registration_date": p["registration_date"],
            "original_completion_date": p["original_completion_date"],
            "revised_completion_date": p["revised_completion_date"],
            "delay_days": p["completion_delay_days"], "extension_count": d.get("extensionCount"),
            "extensions": d.get("extensions"),
        },
        "filings": {
            # The registry does not publish a filing log; the latest signed certificate is the closest date.
            "last_filing_date": p["certificate_date"], "application_date": p["application_date"],
            "certificate_status": d.get("certificateStatus"),
        },
        "progress": {
            "work_done_percent": p["work_done_percent"], "building_count": d.get("buildingCount"),
            "buildings": d.get("buildings"), "construction_tasks": d.get("constructionTasks"),
            "common_facilities": d.get("commonFacilities"),
        },
        "sales": {
            "total_units": total, "sold": sold, "booked": booked, "unsold": p["unsold_units"],
            "sold_pct": round(((sold or 0) + (booked or 0)) * 100 / total, 2) if total else None,
            "has_unit_data": p["has_unit_data"],
            "price_min": m.money(p["price_min"], rate), "price_max": m.money(p["price_max"], rate),
        },
        "size_bands": bands,
        "price_per_sqft": ppsf,
        "legal": {
            "complaint_count": p["complaint_count"], "complaints": d.get("complaints"),
            "appeal_count": d.get("appealCount"), "appeals": d.get("appeals"),
            "litigation_count": p["litigation_count"], "pending_litigation_count": p["pending_litigation_count"],
            "litigations": litigations, "has_encumbrance": d.get("hasEncumbrance"),
            "encumbrances": d.get("encumbrances"),
        },
        "finance": {
            "total_cost": m.money(p["total_cost"], rate), "financing": d.get("financing"),
            "project_bank": d.get("projectBank"),
        },
        "land": {
            "land_area_sqm": d.get("landAreaSqm"), "built_up_area_sqm": d.get("builtUpAreaSqm"),
            "planning_authority": d.get("planningAuthority"), "plot_numbers": d.get("plotNumbers"),
        },
    }


@app.get("/v1/projects/{rera_id}/snapshots", tags=["projects"], summary="History of one project")
def project_snapshots(rera_id: str, con=Depends(get_con), _=Depends(require_key)) -> list[dict]:
    """One row per day the project was loaded: the numbers that move over time."""
    p = find_project(con, rera_id)
    return con.execute(
        """SELECT snapshot_date, registration_status, revised_completion_date, completion_delay_days,
                  total_units, sold_units, booked_units, unsold_units, work_done_percent,
                  price_per_sqft, complaint_count, litigation_count
           FROM project_snapshots WHERE project_id = %s ORDER BY snapshot_date""", (p["project_id"],)).fetchall()


@app.get("/v1/projects/{rera_id}/units", tags=["projects"], summary="Apartments of one project")
def project_units(rera_id: str, status: str | None = Query(None, description="sold | booked | unsold"),
                  limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0),
                  con=Depends(get_con), _=Depends(require_key)) -> list[dict]:
    p = find_project(con, rera_id)
    rate = m.usd_rate(con)
    rows = con.execute(
        """SELECT building, wing, unit_no, floor, status, carpet_area_sqft, size_band, price_inr, price_per_sqft
           FROM units WHERE project_id = %s AND (%s::text IS NULL OR status = %s)
           ORDER BY building, wing, unit_no LIMIT %s OFFSET %s""",
        (p["project_id"], status, status, limit, offset)).fetchall()
    return [{**r, "price": m.money(r.pop("price_inr"), rate), "price_per_sqft": m.money(r["price_per_sqft"], rate)}
            for r in rows]


# The built landing page (src/frontend/dist), served at / when it exists. Registered last, so
# every API route above wins over a file of the same name. Build it with ./startup.sh.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
