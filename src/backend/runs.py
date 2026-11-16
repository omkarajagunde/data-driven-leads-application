"""Fire-and-forget Apify runs: start them, walk away, collect the results later.

`start_run` launches one actor run on Apify's servers and records it in ingest_runs with
status 'started'. Nothing waits: the laptop can sleep. Each run gets a hard spend cap
(enforced by Apify) and a 48-hour time limit, and its dataset is given a name so Apify keeps it
until it is deleted instead of expiring with the plan's retention period.

`collect` looks at every started run. A finished run is downloaded page by page into
data/raw/<dataset name>.jsonl (resuming where a broken download stopped), then loaded into
Postgres from that file, so an offline copy always exists. Safe to run as often as you like.
"""
import inspect
import json
from datetime import datetime, timedelta
from decimal import Decimal

from psycopg.types.json import Jsonb

import db
import env

RAW_DIR = db.ROOT / "data" / "raw"
PAGE = 500  # dataset items per download request
RUN_TIMEOUT = timedelta(hours=48)
FINISHED = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT", "TIMED_OUT"}


def where(path) -> str:
    """A path as the README shows it: relative to the repo when it is inside it."""
    try:
        return str(path.relative_to(db.ROOT))
    except ValueError:
        return str(path)


def client():
    from apify_client import ApifyClient
    return ApifyClient(env.require("APIFY_TOKEN"))  # from .env; never printed


def as_dict(obj) -> dict:
    """apify-client 1.x/2.x return dicts, 3.x returns pydantic models."""
    if obj is None or isinstance(obj, dict):
        return obj or {}
    return obj.model_dump(by_alias=True, mode="json")


def _start_kwargs(fn, run_input: dict, max_cost: float, memory_mb: int) -> dict:
    """Map our options onto whichever argument names this apify-client version uses."""
    params = inspect.signature(fn).parameters
    kw = {"run_input": run_input}
    if "max_total_charge_usd" in params:
        kw["max_total_charge_usd"] = Decimal(str(round(max_cost, 2)))
    if "memory_mbytes" in params:
        kw["memory_mbytes"] = memory_mb
    elif "memory" in params:
        kw["memory"] = memory_mb
    # A full registry scan with details runs for hours; the actor's default timeout would cut it off.
    # (`timeout` in newer clients is the HTTP request timeout, not the run's, so it is left alone.)
    if "run_timeout" in params:
        kw["run_timeout"] = RUN_TIMEOUT
    elif "timeout_secs" in params:
        kw["timeout_secs"] = int(RUN_TIMEOUT.total_seconds())
    return kw


def start_run(con, actor: str, run_input: dict, step: str, name: str, max_cost: float,
              memory_mb: int = 1024) -> dict:
    """Start one run and record it. Returns the ingest_runs row values."""
    api = client()
    fn = api.actor(actor).start
    run = as_dict(fn(**_start_kwargs(fn, run_input, max_cost, memory_mb)))
    dataset_id = run.get("defaultDatasetId")
    try:  # a named dataset is kept until deleted; unnamed ones expire with the plan's retention
        api.dataset(dataset_id).update(name=name)
    except Exception as e:  # naming is a safety net, not a reason to lose the run
        print(f"  (could not name dataset {dataset_id}: {e})")
    con = db.alive(con)
    row = con.execute(
        """INSERT INTO ingest_runs(source, step, input, status, apify_actor, apify_run_id, apify_dataset_id,
                                   dataset_name, max_cost_usd)
           VALUES ('apify', %s, %s, 'started', %s, %s, %s, %s, %s) RETURNING run_id""",
        (step, Jsonb(run_input), actor, run.get("id"), dataset_id, name, max_cost)).fetchone()
    con.commit()
    shown = {k: (f"<{len(v)} values>" if isinstance(v, list) and len(v) > 6 else v) for k, v in run_input.items()}
    print(f"  started {name}: run {run.get('id')} (cap ${max_cost:.2f}) {json.dumps(shown)}")
    return {"run_id": row["run_id"], "apify_run_id": run.get("id")}


def _download(api, r, path) -> int:
    """Append the dataset's items to a JSON Lines file, resuming after the lines already there."""
    have = 0
    if path.exists():
        with path.open("rb") as f:
            have = sum(1 for _ in f)
    total = have
    with path.open("a", encoding="utf-8") as out:
        while True:
            page = as_dict(api.dataset(r["apify_dataset_id"]).list_items(offset=total, limit=PAGE))
            items = page.get("items") or []
            for it in items:
                out.write(json.dumps(it, ensure_ascii=False) + "\n")
            total += len(items)
            if len(items) < PAGE:
                break
            if total % 5000 < PAGE:
                print(f"    downloaded {total:,} items")
    return total


def load_file(con, path, loader) -> tuple[int, int, int]:
    """Load a JSON Lines file (or a saved JSON blob) item by item. Returns (items, projects, unit rows)."""
    con = db.alive(con)
    n = saved = units = 0

    def items():
        if path.suffix == ".jsonl":
            with path.open(encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        yield json.loads(line)
        else:
            blob = json.loads(path.read_text())
            yield from (blob.get("items", []) if isinstance(blob, dict) else blob)

    for it in items():
        n += 1
        res = loader.upsert_project(con, it, source="apify")
        if res:
            saved += 1
            units += res[1]
        if n % 200 == 0:
            con.commit()
        if n % 5000 == 0:
            print(f"    loaded {n:,} items")
    con.commit()
    return n, saved, units


def collect(con, loaders: dict) -> None:
    con = db.alive(con)
    rows = con.execute("""SELECT run_id, step, apify_actor, apify_run_id, apify_dataset_id, dataset_name, started_at
                          FROM ingest_runs WHERE status IN ('started', 'downloaded') ORDER BY run_id""").fetchall()
    if not rows:
        print("no runs waiting to be collected")
        return
    api = client()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    waiting = 0
    for r in rows:
        run = as_dict(api.run(r["apify_run_id"]).get())
        status = run.get("status")
        cost = run.get("usageTotalUsd")
        if status not in FINISHED:
            waiting += 1
            ds = as_dict(api.dataset(r["apify_dataset_id"]).get())
            age = datetime.now(r["started_at"].tzinfo) - r["started_at"]
            print(f"{r['dataset_name']}: {status}, {ds.get('itemCount', 0):,} items so far, "
                  f"${cost or 0:.2f} spent, running {str(age).split('.')[0]}")
            continue
        path = RAW_DIR / f"{r['dataset_name']}.jsonl"
        print(f"{r['dataset_name']}: {status}, ${cost or 0:.2f}; downloading to {where(path)}")
        total = _download(api, r, path)
        con = db.alive(con)
        con.execute("UPDATE ingest_runs SET status='downloaded', raw_file=%s WHERE run_id=%s",
                    (where(path), r["run_id"]))
        con.commit()
        n, saved, units = load_file(con, path, loaders[r["apify_actor"]])
        con = db.alive(con)
        note = None if status == "SUCCEEDED" else f"run ended {status}; partial results loaded"
        con.execute("""UPDATE ingest_runs SET status='collected', finished_at=now(), rows_in=%s, rows_upserted=%s,
                           unit_rows=%s, cost_usd=%s, notes=%s WHERE run_id=%s""",
                    (n, saved, units, cost, note, r["run_id"]))
        con.commit()
        print(f"  {total:,} items downloaded; {saved:,} projects and {units:,} apartment rows loaded")
    if waiting:
        print(f"{waiting} run(s) still running; run `collect` again later")
