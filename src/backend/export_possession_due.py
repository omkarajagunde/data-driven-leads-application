#!/usr/bin/env python3
"""Product #1: possession-due list. Projects whose (revised) completion date falls in the next N days,
grouped by pincode/taluka, with unit counts. Output CSV in data/exports/.

  python3 src/backend/export_possession_due.py --days 120 --min-units 50
  python3 src/backend/export_possession_due.py --days 90 --pincodes 411057,411033,411045 --out wakad_q1.csv
"""
import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--min-units", type=int, default=20)
    ap.add_argument("--district", default="Pune")
    ap.add_argument("--pincodes", help="comma-separated filter")
    ap.add_argument("--out")
    a = ap.parse_args()

    today, horizon = date.today(), date.today() + timedelta(days=a.days)
    sql = """SELECT rera_id, project_name, developer_name, taluka, pincode, address, latitude, longitude,
                    property_type, registration_status, registration_date, revised_completion_date,
                    total_units, sold_units, work_done_percent, complaint_count
             FROM projects
             WHERE district = %s AND revised_completion_date BETWEEN %s AND %s
               AND COALESCE(total_units, 0) >= %s
               AND COALESCE(registration_status, '') NOT IN ('Lapsed', 'Revoked')"""
    params = [a.district, today, horizon, a.min_units]
    if a.pincodes:
        sql += " AND pincode = ANY(%s)"
        params.append([p.strip() for p in a.pincodes.split(",")])
    sql += " ORDER BY pincode, revised_completion_date"

    with db.connect() as con:
        rows = con.execute(sql, params).fetchall()
    out = Path(a.out) if a.out else db.ROOT / "data" / "exports" / f"possession_due_{a.district.lower()}_{today}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(list(rows[0].keys()) if rows else ["no rows"])
        for r in rows:
            w.writerow(list(r.values()))
    units = sum((r["total_units"] or 0) for r in rows)
    print(f"{len(rows)} projects, {units} units due between {today} and {horizon} -> {out}")


if __name__ == "__main__":
    main()
