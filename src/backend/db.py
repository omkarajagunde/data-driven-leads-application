"""Postgres helpers shared by the driver, the API and the export scripts."""
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import env

ROOT = Path(__file__).resolve().parents[2]  # repo root (this file is in src/backend)
SCHEMA = ROOT / "db" / "schema.sql"
REGIONS_FILE = ROOT / "config" / "regions.json"
DEFAULT_INR_PER_USD = 88.0  # placeholder; override with FX_INR_PER_USD in .env or update fx_rates


def connect() -> psycopg.Connection:
    """Open a connection using DATABASE_URL from .env (rows come back as dicts)."""
    return psycopg.connect(env.require("DATABASE_URL"), row_factory=dict_row)


def alive(con) -> psycopg.Connection:
    """Return `con` if it still works, otherwise a new connection (e.g. after a Postgres restart)."""
    try:
        con.execute("SELECT 1")
        con.commit()
        return con
    except psycopg.Error:
        return connect()


def init_schema(con) -> None:
    con.execute(SCHEMA.read_text())
    rate = float(os.environ.get("FX_INR_PER_USD") or DEFAULT_INR_PER_USD)
    con.execute("INSERT INTO fx_rates(currency, inr_per_unit) VALUES ('USD', %s) ON CONFLICT DO NOTHING", (rate,))
    con.commit()


def sync_regions(con, path: Path = REGIONS_FILE) -> dict:
    """Mirror config/regions.json into regions / zones / pincodes. The file is the source of truth:
    rows that are no longer in it are removed (projects are never touched)."""
    cfg = json.loads(path.read_text())
    seen_regions, seen_zones, seen_pins = [], [], {}
    for r in cfg["regions"]:
        rera, apify = r.get("rera") or {}, r.get("apify") or {}
        extra = {k: v for k, v in r.items() if k not in ("id", "name", "state", "rera", "apify", "zones")}
        con.execute(
            """INSERT INTO regions(region_id, name, state, rera_authority, rera_website, apify_actor, apify_status, extra)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (region_id) DO UPDATE SET name=excluded.name, state=excluded.state,
                   rera_authority=excluded.rera_authority, rera_website=excluded.rera_website,
                   apify_actor=excluded.apify_actor, apify_status=excluded.apify_status,
                   extra=excluded.extra, updated_at=now()""",
            (r["id"], r["name"], r.get("state"), rera.get("authority"), rera.get("website"),
             apify.get("actor"), apify.get("status"), Jsonb(extra)),
        )
        seen_regions.append(r["id"])
        for z in r["zones"]:
            con.execute(
                """INSERT INTO zones(region_id, zone_id, name) VALUES (%s,%s,%s)
                   ON CONFLICT (region_id, zone_id) DO UPDATE SET name=excluded.name""",
                (r["id"], z["id"], z["name"]),
            )
            seen_zones.append((r["id"], z["id"]))
            for d in z["districts"]:
                for p in d["pincodes"]:
                    if p["code"] in seen_pins:
                        raise SystemExit(f"pincode {p['code']} appears twice in {path.name} "
                                         f"({seen_pins[p['code']]} and {r['id']}/{z['id']})")
                    seen_pins[p["code"]] = f"{r['id']}/{z['id']}"
                    con.execute(
                        """INSERT INTO pincodes(pincode, region_id, zone_id, district_id, district_name, areas, latitude, longitude)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (pincode) DO UPDATE SET region_id=excluded.region_id, zone_id=excluded.zone_id,
                               district_id=excluded.district_id, district_name=excluded.district_name, areas=excluded.areas,
                               latitude=COALESCE(excluded.latitude, pincodes.latitude),
                               longitude=COALESCE(excluded.longitude, pincodes.longitude)""",
                        (p["code"], r["id"], z["id"], d["id"], d["name"], Jsonb(p.get("areas") or []),
                         p.get("latitude"), p.get("longitude")),
                    )
    # Guard: a config edited by mistake (a region dropped, an empty list) must not quietly remove
    # pincodes, because their real outlines go with them. Removing a few is normal upkeep; removing
    # many needs SYNC_ALLOW_PRUNE=1. Nothing has been committed yet, so stopping here changes nothing.
    gone = con.execute("SELECT pincode FROM pincodes WHERE NOT (pincode = ANY(%s))", (list(seen_pins),)).fetchall()
    have = con.execute("SELECT count(*) AS n FROM pincodes").fetchone()["n"]
    if gone and (not seen_pins or len(gone) > max(5, have // 10)) and os.environ.get("SYNC_ALLOW_PRUNE") != "1":
        con.rollback()
        raise SystemExit(
            f"{path.name} would remove {len(gone)} of {have} pincodes (and their outlines), e.g. "
            f"{', '.join(r['pincode'] for r in gone[:8])}. If that is intended, run again with SYNC_ALLOW_PRUNE=1.")
    con.execute("DELETE FROM pincodes WHERE NOT (pincode = ANY(%s))", (list(seen_pins),))
    con.execute("DELETE FROM zones WHERE NOT ((region_id || '/' || zone_id) = ANY(%s))",
                ([f"{a}/{b}" for a, b in seen_zones],))
    con.execute("DELETE FROM regions WHERE NOT (region_id = ANY(%s))", (seen_regions,))
    con.commit()
    return {"regions": len(seen_regions), "zones": len(seen_zones), "pincodes": len(seen_pins)}


def start_run(con, source: str, step: str, input_obj) -> int:
    row = con.execute(
        "INSERT INTO ingest_runs(source, step, input) VALUES (%s,%s,%s) RETURNING run_id",
        (source, step, Jsonb(input_obj) if input_obj is not None else None),
    ).fetchone()
    con.commit()
    return row["run_id"]


def finish_run(con, run_id: int, rows_in: int, rows_upserted: int, unit_rows: int = 0,
               cost_usd=None, notes: str | None = None) -> None:
    con.execute(
        """UPDATE ingest_runs SET finished_at=now(), rows_in=%s, rows_upserted=%s, unit_rows=%s,
               cost_usd=%s, notes=%s WHERE run_id=%s""",
        (rows_in, rows_upserted, unit_rows, cost_usd, notes, run_id),
    )
    con.commit()
