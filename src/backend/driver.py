#!/usr/bin/env python3
"""Driver: walk config/regions.json, fetch RERA data through each region's Apify actor, fill Postgres.

Commands
  init      create tables and mirror config/regions.json into regions / zones / pincodes
  start     launch Apify runs and return at once (fire and forget); see "Full load" below
  collect   download every finished run to data/raw/ and load it; safe to run any time
  runs      list fire-and-forget runs and their state
  load      load raw JSON / JSONL files already saved in data/raw (free, no Apify call)
  fetch     the older, waiting variant: run the actor, wait, load (small targeted fetches)
  status    row counts per region

Full load (every project in the pincodes of regions.json)
  The registry has no location search, so one scan reads every project file once and keeps the
  districts our pincodes are in, with details, complaints and apartments switched on. It is split
  into registry-id slices that run in parallel, so each file is still read only once.

  python3 src/backend/driver.py start test                         # ~$1-3: newest files, Pune only
  python3 src/backend/driver.py start full --parallel 4 --max-cost 65
  python3 src/backend/driver.py collect                            # later, as often as you like

Every two weeks
  python3 src/backend/driver.py start delta --max-cost 15          # new registrations + changed projects
  python3 src/backend/driver.py collect

The MahaRERA registry has no search, so the actor reads project files newest-first and charges a
little for every project it reads and drops. Asking for one pincode at a time would re-read the
registry once per pincode, so `fetch` works in two steps instead:

  1. scan     registry rows only (cheap), filtered to the pincodes of the chosen regions, 100
              pincodes per run (the actor's limit). --scan-max caps how many matching projects
              are kept in total (0 = the whole registry).
  2. details  the full file (buildings, progress, court cases, complaints, apartments) for
              --per-pincode projects in each pincode (0 = every project), fetched by RERA number,
              which costs nothing for filtering.

Examples
  python3 src/backend/driver.py init
  python3 src/backend/driver.py load data/raw/*.json
  python3 src/backend/driver.py fetch --scan-max 2000 --per-pincode 3 --max-cost 5      # small test
  python3 src/backend/driver.py fetch --regions pune-city pmrda --scan-max 0 --per-pincode 0 --max-cost 60   # everything
  python3 src/backend/driver.py fetch --details-only --per-pincode 3                    # reuse projects already in the DB
"""
import argparse
import hashlib
import json
import math
import os
import sys
import zlib
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402
import env  # noqa: E402
import maharera  # noqa: E402
import runs  # noqa: E402

RAW_DIR = db.ROOT / "data" / "raw"
# One loader per actor. A region whose actor is not listed here (or is not 'in-use') is skipped.
LOADERS = {"nice_dev/maharera-projects-scraper": maharera}
MAX_LOCATIONS = 100  # actor limit on input.locations
BASE_INPUT = {
    "includeAgents": False,
    "includeProfessionals": False,
    "includeComplainantNames": False,          # personal data: never pull it
    "proxyConfiguration": {"useApifyProxy": False},
}


def load_items(con, items: list[dict], loader, source: str, step: str, input_obj, cost=None, notes=None) -> int:
    con = db.alive(con)  # an actor run can take an hour; the database may have restarted meanwhile
    run_id = db.start_run(con, source, step, input_obj)
    n = units = 0
    for it in items:
        res = loader.upsert_project(con, it, source="apify")
        if res:
            n += 1
            units += res[1]
    con.commit()
    db.finish_run(con, run_id, len(items), n, units, cost, notes)
    print(f"  loaded {n} projects, {units} apartment rows")
    return n


def run_actor(actor: str, run_input: dict, step: str, wait: int, max_cost: float) -> tuple[list[dict], float | None]:
    from apify_client import ApifyClient
    client = ApifyClient(env.require("APIFY_TOKEN"))  # from .env; never printed
    shown = {k: (f"<{len(v)} values>" if isinstance(v, list) and len(v) > 5 else v) for k, v in run_input.items()}
    print(f"  starting {actor} [{step}] {json.dumps(shown)} (spend cap ${max_cost})")
    kwargs = {"run_input": run_input, "wait_duration": timedelta(seconds=wait)}
    try:
        run = client.actor(actor).call(max_total_charge_usd=Decimal(str(max_cost)), **kwargs)
    except TypeError:  # older apify-client: no spend cap / wait in seconds
        run = client.actor(actor).call(run_input=run_input, wait_secs=wait)
    if run is None:
        sys.exit(f"actor run did not finish within {wait}s; check https://console.apify.com/actors/runs")
    if not isinstance(run, dict):  # apify-client >= 3 returns a pydantic model
        run = run.model_dump(by_alias=True, mode="json")
    status, cost = run.get("status"), run.get("usageTotalUsd")
    print(f"  run {run.get('id')} finished: status={status} cost=${cost}")
    if status != "SUCCEEDED":
        sys.exit(f"actor run did not succeed: {status}")
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = RAW_DIR / f"apify_{datetime.now():%Y%m%d_%H%M%S}_{step}.json"
    out.write_text(json.dumps({"input": run_input, "run": {"id": run.get("id"), "cost_usd": cost},
                               "items": items}, ensure_ascii=False))
    print(f"  saved {len(items)} items to {out.relative_to(db.ROOT)}")
    return items, cost


def cmd_init(con, a):
    db.init_schema(con)
    print("schema ready;", db.sync_regions(con))
    # The landing page calls the API with FRONTEND_API_KEY (added on the server, never in the
    # browser). Register it here so a brand-new database accepts it; only its hash is stored.
    env.load_dotenv()
    key = os.environ.get("FRONTEND_API_KEY")
    if key:
        added = con.execute(
            """INSERT INTO api_keys(key_hash, key_prefix, label) VALUES (%s, %s, 'frontend')
               ON CONFLICT (key_hash) DO NOTHING RETURNING key_id""",
            (hashlib.sha256(key.encode()).hexdigest(), key[:8])).fetchone()
        con.commit()
        print("frontend API key registered" if added else "frontend API key already registered")
    else:
        print("FRONTEND_API_KEY is not set: the landing page will get 401s until it is")


def cmd_load(con, a):
    db.init_schema(con)
    db.sync_regions(con)
    for f in a.files:
        if f.endswith(".jsonl"):  # a downloaded run: stream it line by line
            run_id = db.start_run(con, "file", "load-file", None)
            n, saved, units = runs.load_file(con, Path(f), maharera)
            db.finish_run(db.alive(con), run_id, n, saved, units, None, Path(f).name)
            print(f"{f}: {n:,} items, {saved:,} projects, {units:,} apartment rows")
            continue
        blob = json.loads(Path(f).read_text())
        items = blob.get("items", []) if isinstance(blob, dict) else blob
        print(f"{f}: {len(items)} items")
        load_items(con, items, maharera, "file", "load-file", blob.get("input") if isinstance(blob, dict) else None,
                   notes=Path(f).name)


def cmd_fetch(con, a):
    db.init_schema(con)
    db.sync_regions(con)
    regions = con.execute("SELECT region_id, name, apify_actor, apify_status FROM regions ORDER BY region_id").fetchall()
    if a.regions:
        unknown = set(a.regions) - {r["region_id"] for r in regions}
        if unknown:
            sys.exit(f"unknown region(s): {', '.join(sorted(unknown))}")
        regions = [r for r in regions if r["region_id"] in a.regions]
    by_actor: dict[str, list] = {}
    for r in regions:
        if r["apify_status"] != "in-use" or r["apify_actor"] not in LOADERS:
            print(f"skipping {r['name']}: actor {r['apify_actor']} is '{r['apify_status']}' / has no loader")
            continue
        by_actor.setdefault(r["apify_actor"], []).append(r["region_id"])

    spent = 0.0
    for actor, region_ids in by_actor.items():
        loader = LOADERS[actor]
        pins = [r["pincode"] for r in con.execute(
            "SELECT pincode FROM pincodes WHERE region_id = ANY(%s) ORDER BY pincode", (region_ids,))]
        print(f"{actor}: regions {', '.join(region_ids)} ({len(pins)} pincodes)")

        if not a.details_only:
            # The actor takes at most 100 locations per run, so the pincodes go in batches and
            # --scan-max is shared between the batches.
            batches = [pins[i:i + MAX_LOCATIONS] for i in range(0, len(pins), MAX_LOCATIONS)]
            per_batch = -(-a.scan_max // len(batches)) if a.scan_max else 0
            for n, batch in enumerate(batches, 1):
                if a.batches and n not in a.batches:
                    continue
                remaining = round(a.max_cost - spent, 2)
                if remaining <= 0.05:
                    print(f"  spend cap reached (${spent:.2f}); scan batch {n}/{len(batches)} skipped")
                    break
                scan_input = {**BASE_INPUT, "locations": batch, "maxItems": per_batch,
                              "includeDetails": False, "includeComplaints": False, "includeUnits": False,
                              "maxConcurrency": a.concurrency, "maxRequestsPerMinute": a.rpm}
                items, cost = run_actor(actor, scan_input, f"scan{n}", a.wait, remaining)
                spent += cost or 0
                load_items(con, items, loader, "apify", "scan", scan_input, cost)

        if a.per_pincode < 0:
            continue
        con = db.alive(con)
        # Biggest projects first within each pincode, skipping ones that already have the full file
        # unless --refresh is given.
        rows = con.execute(
            """SELECT rera_id FROM (
                   SELECT p.rera_id, row_number() OVER (PARTITION BY p.pincode
                              ORDER BY p.total_units DESC NULLS LAST, p.registration_date DESC NULLS LAST) AS rn
                   FROM projects p JOIN pincodes pc ON pc.pincode = p.pincode
                   WHERE pc.region_id = ANY(%s) AND p.rera_authority = %s
                     AND (%s OR NOT (p.detail_level = 'details' AND p.has_unit_data))
               ) t WHERE %s = 0 OR rn <= %s""",
            (region_ids, loader.AUTHORITY, a.refresh, a.per_pincode, a.per_pincode)).fetchall()
        numbers = [r["rera_id"] for r in rows]
        if not numbers:
            print("  no projects need details")
            continue
        for i in range(0, len(numbers), 5000):
            chunk = numbers[i:i + 5000]
            remaining = round(a.max_cost - spent, 2)
            if remaining <= 0.05:
                print(f"  spend cap reached (${spent:.2f}); {len(numbers) - i} projects left without details")
                break
            det_input = {**BASE_INPUT, "registrationNumbers": chunk, "maxItems": 0,
                         "includeDetails": True, "includeComplaints": True, "includeUnits": True,
                         "maxConcurrency": a.concurrency, "maxRequestsPerMinute": a.rpm}
            items, cost = run_actor(actor, det_input, "details", a.wait, remaining)
            spent += cost or 0
            load_items(con, items, loader, "apify", "details", det_input, cost)
    print(f"done; Apify spend this command: ${spent:.2f}")
    cmd_status(db.alive(con), a)


# ---------------------------------------------------------------- fire and forget
# Projects that will not change any more; the two-weekly delta leaves them to a quarterly check.
CLOSED = ("completed", "lapsed", "de-registered", "deregistered", "revoked", "abeyance")
DELTA_BUCKETS = 6        # fixed, so each bucket keeps its own Apify memory between runs
MAX_NUMBERS = 10_000     # actor limit on registrationNumbers per run
DEFAULT_REGISTRY_TOP = 70_000


def in_use_regions(con, wanted=None) -> tuple[str, list[str]]:
    """The one actor in use and the regions it serves (optionally only `wanted`)."""
    rows = con.execute("SELECT region_id, apify_actor, apify_status FROM regions ORDER BY region_id").fetchall()
    if wanted:
        unknown = set(wanted) - {r["region_id"] for r in rows}
        if unknown:
            sys.exit(f"unknown region(s): {', '.join(sorted(unknown))}")
        rows = [r for r in rows if r["region_id"] in wanted]
    ok = [r for r in rows if r["apify_status"] == "in-use" and r["apify_actor"] in LOADERS]
    for r in rows:
        if r not in ok:
            print(f"skipping {r['region_id']}: actor {r['apify_actor']} is '{r['apify_status']}' / has no loader")
    actors = {r["apify_actor"] for r in ok}
    if len(actors) != 1:
        sys.exit("start works on regions that share one in-use actor")
    return actors.pop(), [r["region_id"] for r in ok]


def districts(con, region_ids) -> list[str]:
    """District names as the registry spells them (from projects already loaded), plus the names in
    regions.json. A name the registry does not use simply matches nothing."""
    seen = {r["district"] for r in con.execute(
        """SELECT p.district FROM projects p JOIN pincodes pc ON pc.pincode = p.pincode
           WHERE pc.region_id = ANY(%s) AND p.district IS NOT NULL
           GROUP BY p.district HAVING count(*) >= 3""", (region_ids,))}
    config = {r["district_name"] for r in con.execute(
        "SELECT DISTINCT district_name FROM pincodes WHERE region_id = ANY(%s) AND district_name IS NOT NULL",
        (region_ids,))}
    return sorted(seen | config)


def registry_top(con) -> int:
    """Highest registry file id seen so far (project pages end in /view/<id>)."""
    row = con.execute(r"""SELECT max((regexp_match(source_url, '/view/(\d+)'))[1]::int) AS top
                          FROM projects WHERE source_url LIKE '%/view/%'""").fetchone()
    return row["top"] or DEFAULT_REGISTRY_TOP


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M")


def cmd_start(con, a):
    db.init_schema(con)
    db.sync_regions(con)
    detail = {"includeDetails": True, "includeComplaints": True, "includeUnits": True,
              "maxConcurrency": a.concurrency, "maxRequestsPerMinute": a.rpm, "minRequestIntervalMs": a.gap_ms}

    if a.mode in ("full", "test"):
        actor, region_ids = in_use_regions(con, a.regions or (["pune-city"] if a.mode == "test" else None))
        names = districts(con, region_ids)
        top = registry_top(con)
        base = {**BASE_INPUT, **detail, "locations": names, "maxItems": 0, "maxItemsPerQuery": 0}
        if a.mode == "test":
            # The newest files only: enough to measure the real share of matches and the cost per project.
            slices = [(max(1, top - a.test_files), None)]
        else:
            # Registry-id slices; the newest is open-ended so files registered during the run are not missed.
            size = math.ceil(top / a.parallel)
            slices = [(i * size + 1, (i + 1) * size if i < a.parallel - 1 else None) for i in range(a.parallel)]
            if a.slices:  # re-run only some slices (e.g. one the registry cut short); same split, same share of the cap
                bad = [n for n in a.slices if not 1 <= n <= a.parallel]
                if bad:
                    sys.exit(f"--slices must be between 1 and {a.parallel}")
                share = a.max_cost / a.parallel
                for n in a.slices:
                    lo, hi = slices[n - 1]
                    run_input = {**base, "projectIdFrom": lo, **({"projectIdTo": hi} if hi else {})}
                    runs.start_run(con, actor, run_input, "full-scan", f"subak-full-{stamp()}-s{n}", share)
                print("Started. Close the laptop if you like; run `driver.py collect` later.")
                return
        print(f"{actor}: {a.mode} scan of {', '.join(names)} for regions {', '.join(region_ids)}; "
              f"registry ids up to ~{top:,} in {len(slices)} slice(s)")
        for i, (lo, hi) in enumerate(slices, 1):
            run_input = {**base, "projectIdFrom": lo, **({"projectIdTo": hi} if hi else {})}
            runs.start_run(con, actor, run_input, f"{a.mode}-scan", f"subak-{a.mode}-{stamp()}-s{i}",
                           a.max_cost / len(slices))

    else:  # delta
        actor, region_ids = in_use_regions(con, a.regions)
        names = districts(con, region_ids)
        rows = con.execute(
            """SELECT p.rera_id, lower(coalesce(p.registration_status, '')) AS st FROM projects p
               JOIN pincodes pc ON pc.pincode = p.pincode
               WHERE pc.region_id = ANY(%s) AND p.rera_authority = %s""",
            (region_ids, maharera.AUTHORITY)).fetchall()
        numbers = [r["rera_id"] for r in rows if (r["st"] in CLOSED) == a.include_closed]
        buckets: dict[int, list[str]] = {}
        for n in numbers:  # crc32 keeps a project in the same bucket (and the same Apify memory) every time
            buckets.setdefault(zlib.crc32(n.encode()) % DELTA_BUCKETS, []).append(n)
        jobs = []
        if not a.include_closed:
            # New registrations of the last 30 days, so a two-weekly run overlaps the previous one.
            jobs.append(("delta-new", "new", {**BASE_INPUT, **detail, "locations": names, "maxItems": 0,
                                              "postedAfter": "30 days", "onlyNew": True, "alsoChanged": False,
                                              "stateKey": "subak-new"}))
        tag = "closed" if a.include_closed else "progress"
        for b, nums in sorted(buckets.items()):
            for j in range(0, len(nums), MAX_NUMBERS):
                jobs.append((f"delta-{tag}", f"{tag}{b}" + (f"-{j // MAX_NUMBERS}" if j else ""),
                             {**BASE_INPUT, **detail, "registrationNumbers": nums[j:j + MAX_NUMBERS], "maxItems": 0,
                              "onlyNew": True, "alsoChanged": True, "stateKey": f"subak-{tag}-{b}"}))
        print(f"{actor}: delta for {', '.join(region_ids)}: {len(numbers):,} {tag} projects in "
              f"{len(buckets)} bucket(s)" + ("" if a.include_closed else " + new registrations"))
        for step, label, run_input in jobs:
            runs.start_run(con, actor, run_input, step, f"subak-delta-{stamp()}-{label}", a.max_cost / len(jobs))
    print("Started. Close the laptop if you like; run `driver.py collect` later.")


PAGE_URL = "https://maharerait.maharashtra.gov.in/public/project/view/{}"
MAX_START_URLS = 1000  # actor limit per run


def cmd_pages(con, a):
    """Read registry project pages directly, in batches, a few runs at a time.

    The registry's list pages (which a scan needs first) can be too slow for the actor's early stop;
    project pages are not. Each batch is one run over 1,000 consecutive registry ids, newest first,
    kept only for our districts. Batches already collected are skipped, so a re-run resumes.
    This command stays running (start it with `caffeinate` on a Mac) until every batch is done."""
    import time
    db.init_schema(con)
    db.sync_regions(con)
    actor, region_ids = in_use_regions(con, a.regions)
    names = districts(con, region_ids)
    hi = a.to_id or registry_top(con)
    batches = [(max(a.from_id, top - a.batch + 1), top) for top in range(hi, a.from_id - 1, -a.batch)]
    detail = {"includeDetails": True, "includeComplaints": True, "includeUnits": True,
              "maxConcurrency": a.concurrency, "maxRequestsPerMinute": a.rpm}
    if a.gap_ms:
        detail["minRequestIntervalMs"] = a.gap_ms
    name = lambda lo, top: f"subak-pages-{lo}-{top}"  # noqa: E731 - stable, so a re-run recognises its batches
    rows = con.execute("SELECT dataset_name, status, rows_upserted, cost_usd, notes FROM ingest_runs "
                       "WHERE dataset_name LIKE 'subak-pages-%' ORDER BY run_id").fetchall()
    spent = sum(float(r["cost_usd"] or 0) for r in rows)
    # A batch counts as done once it saved something or ended normally; one the site cut short with
    # nothing saved is tried again. (Several attempts of one batch share its name; the last one counts.)
    last = {r["dataset_name"]: r for r in rows}
    cut_short = lambda r: (r["status"] == "collected" and not r["rows_upserted"]  # noqa: E731
                           and (r["notes"] or "").startswith("run ended"))
    todo = [(lo, top) for lo, top in batches if not last.get(name(lo, top)) or cut_short(last[name(lo, top)])]
    stamp_ = lambda: datetime.now().strftime("%H:%M")  # noqa: E731
    retry = sum(1 for lo, top in todo if last.get(name(lo, top)))
    print(f"{actor}: pages {a.from_id}-{hi} for {', '.join(names)}: {len(batches)} batches, "
          f"{len(batches) - len(todo)} already done, {len(todo)} to go ({retry} of them retries); "
          f"cap ${a.max_cost:.2f} (${spent:.2f} already spent)")

    # Pick up batches started by an earlier invocation that are still running.
    running = {r["run_id"]: r["dataset_name"] for r in con.execute(
        "SELECT run_id, dataset_name FROM ingest_runs WHERE dataset_name LIKE 'subak-pages-%' AND status IN ('started','downloaded')")}
    api = runs.client()
    per_batch = round(a.batch * 0.00106 + 0.02, 2)  # every page kept with full details, the worst case
    while todo or running:
        # Collect whatever has finished.
        if running:
            runs.collect(con, LOADERS, only=list(running), quiet=True)
            con = db.alive(con)
            for r in con.execute("SELECT run_id, dataset_name, rows_upserted, cost_usd, notes FROM ingest_runs "
                                 "WHERE run_id = ANY(%s) AND status = 'collected'", (list(running),)):
                spent += float(r["cost_usd"] or 0)
                print(f"[{stamp_()}] {r['dataset_name']}: {r['rows_upserted']} projects, ${float(r['cost_usd'] or 0):.2f}"
                      f"{' (' + r['notes'] + ')' if r['notes'] else ''}; total spent ${spent:.2f}", flush=True)
                running.pop(r["run_id"])
        # Start new batches while there is room and money.
        live = sum(float(runs.as_dict(api.run(r["apify_run_id"]).get()).get("usageTotalUsd") or 0)
                   for r in con.execute("SELECT apify_run_id FROM ingest_runs WHERE run_id = ANY(%s)", (list(running) or [0],)))
        while todo and len(running) < a.parallel:
            if spent + live + per_batch > a.max_cost:
                print(f"[{stamp_()}] spend cap: ${spent + live:.2f} spent or committed, next batch could cost "
                      f"${per_batch:.2f}; {len(todo)} batches left unstarted", flush=True)
                todo = []
                break
            lo, top = todo.pop(0)
            run_input = {**BASE_INPUT, **detail, "locations": names, "maxItems": 0,
                         "startUrls": [{"url": PAGE_URL.format(i)} for i in range(top, lo - 1, -1)]}
            started = runs.start_run(con, actor, run_input, "pages", name(lo, top), per_batch)
            running[started["run_id"]] = name(lo, top)
            live += per_batch
        if todo or running:
            time.sleep(a.poll)
    print(f"[{stamp_()}] all batches finished; total spent ${spent:.2f}")
    cmd_status(db.alive(con), a)


def cmd_collect(con, a):
    db.init_schema(con)
    db.sync_regions(con)
    runs.collect(con, LOADERS)
    cmd_status(db.alive(con), a)


def cmd_runs(con, a):
    db.init_schema(con)
    rows = con.execute("""SELECT run_id, dataset_name, status, started_at, max_cost_usd, cost_usd, rows_upserted
                          FROM ingest_runs WHERE status IS NOT NULL ORDER BY run_id DESC LIMIT 30""").fetchall()
    if not rows:
        print("no fire-and-forget runs yet")
    for r in rows:
        print(f"{r['run_id']:>4}  {r['status']:<10} {r['dataset_name'] or '':<42} started {r['started_at']:%d %b %H:%M}"
              f"  cap ${r['max_cost_usd'] or 0}  spent ${r['cost_usd'] if r['cost_usd'] is not None else '?'}"
              f"  projects {r['rows_upserted'] if r['rows_upserted'] is not None else '-'}")


def cmd_status(con, a):
    rows = con.execute(
        """SELECT r.region_id,
                  (SELECT count(*) FROM pincodes pc WHERE pc.region_id = r.region_id) AS pincodes,
                  count(DISTINCT p.pincode) AS pincodes_with_projects,
                  count(p.project_id) AS projects,
                  count(*) FILTER (WHERE p.detail_level = 'details') AS with_details,
                  count(*) FILTER (WHERE p.has_unit_data) AS with_units
           FROM regions r LEFT JOIN pincodes pc ON pc.region_id = r.region_id
                LEFT JOIN projects p ON p.pincode = pc.pincode
           GROUP BY r.region_id ORDER BY r.region_id""").fetchall()
    print(f"{'region':14}{'pincodes':>9}{'covered':>9}{'projects':>10}{'details':>9}{'units':>7}")
    for r in rows:
        print(f"{r['region_id']:14}{r['pincodes']:>9}{r['pincodes_with_projects']:>9}{r['projects']:>10}"
              f"{r['with_details']:>9}{r['with_units']:>7}")
    other = con.execute("""SELECT count(*) AS n FROM projects p
                           WHERE NOT EXISTS (SELECT 1 FROM pincodes pc WHERE pc.pincode = p.pincode)""").fetchone()
    t = con.execute("SELECT (SELECT count(*) FROM units) AS units, (SELECT count(*) FROM project_snapshots) AS snaps").fetchone()
    print(f"projects outside mapped pincodes: {other['n']}; apartment rows: {t['units']}; snapshots: {t['snaps']}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("status")
    ld = sub.add_parser("load")
    ld.add_argument("files", nargs="+")
    f = sub.add_parser("fetch")
    f.add_argument("--regions", nargs="+", metavar="REGION_ID", help="default: every region whose actor is in-use")
    f.add_argument("--scan-max", type=int, default=2000, help="projects kept by the registry scan; 0 = no limit")
    f.add_argument("--per-pincode", type=int, default=3,
                   help="projects per pincode to fetch in full; 0 = all, -1 = none")
    f.add_argument("--batches", nargs="+", type=int, metavar="N",
                   help="run only these scan batches (1-based), e.g. to resume after a failure")
    f.add_argument("--details-only", action="store_true", help="skip the scan; use projects already in the DB")
    f.add_argument("--refresh", action="store_true", help="re-fetch details for projects that already have them")
    f.add_argument("--max-cost", type=float, default=5.0, help="USD spend cap for this command")
    f.add_argument("--wait", type=int, default=3600, help="seconds to wait for each run")
    f.add_argument("--concurrency", type=int, default=2)   # gentle on the government site
    f.add_argument("--rpm", type=int, default=60)
    st = sub.add_parser("start", help="launch Apify runs and return at once")
    st.add_argument("mode", choices=["test", "full", "delta"])
    st.add_argument("--regions", nargs="+", metavar="REGION_ID",
                    help="default: every region whose actor is in-use (test: pune-city)")
    st.add_argument("--parallel", type=int, default=2, help="full: registry slices run at the same time")
    st.add_argument("--slices", nargs="+", type=int, metavar="N",
                    help="full: start only these slices (1-based), e.g. to re-run one the registry cut short")
    st.add_argument("--max-cost", type=float, help="USD cap for all runs together, split evenly between them "
                                                   "(default: test 3, full 65, delta 15)")
    st.add_argument("--test-files", type=int, default=2000, help="test: how many of the newest registry files to read")
    st.add_argument("--include-closed", action="store_true",
                    help="delta: check completed / lapsed projects instead (quarterly)")
    # Gentle by default: MahaRERA is a public government site. 2 runs x 60 a minute is about two
    # requests a second in total, roughly one person clicking through it.
    st.add_argument("--concurrency", type=int, default=2, help="requests in parallel per run")
    st.add_argument("--rpm", type=int, default=60, help="requests per minute per run")
    st.add_argument("--gap-ms", type=int, default=500, help="smallest gap between two requests of one run")
    pg = sub.add_parser("pages", help="read registry project pages directly, in batches (stays running)")
    pg.add_argument("--regions", nargs="+", metavar="REGION_ID", help="default: every region whose actor is in-use")
    pg.add_argument("--from-id", type=int, required=True, help="lowest registry id to read")
    pg.add_argument("--to-id", type=int, help="highest registry id (default: the newest seen)")
    pg.add_argument("--batch", type=int, default=MAX_START_URLS, help="registry ids per run (max 1000)")
    pg.add_argument("--parallel", type=int, default=2, help="runs at the same time")
    pg.add_argument("--max-cost", type=float, default=20.0, help="USD cap for all batches together")
    pg.add_argument("--concurrency", type=int, default=4, help="requests in parallel per run")
    pg.add_argument("--rpm", type=int, default=300, help="requests per minute per run")
    pg.add_argument("--gap-ms", type=int, default=0, help="smallest gap between two requests of one run")
    pg.add_argument("--poll", type=int, default=60, help="seconds between checks")
    sub.add_parser("collect", help="download and load every finished run")
    sub.add_parser("runs", help="list fire-and-forget runs")
    a = p.parse_args()
    if a.cmd == "start" and a.max_cost is None:
        a.max_cost = {"test": 3.0, "full": 65.0, "delta": 15.0}[a.mode]
    with db.connect() as con:
        {"init": cmd_init, "load": cmd_load, "fetch": cmd_fetch, "status": cmd_status,
         "start": cmd_start, "collect": cmd_collect, "runs": cmd_runs, "pages": cmd_pages}[a.cmd](con, a)


if __name__ == "__main__":
    main()
