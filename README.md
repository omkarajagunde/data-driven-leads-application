# data-driven-leads (Subak)

Public-record + satellite signals for Pune / MMR / Bengaluru, sold as leads and reports. First source: MahaRERA.

## Layout

```
config/regions.json                   regions -> zones -> districts -> pincodes, plus each region's RERA site and Apify actor
docker-compose.yml                    local Postgres + pgweb (browser UI for the database)
db/schema.sql                         Postgres schema
src/backend/driver.py                 walks regions.json, runs the Apify actor, fills Postgres
src/backend/maharera.py               maps one MahaRERA actor item onto projects / units / snapshots
src/backend/metrics.py                the metrics block behind the map (region / zone / pincode)
src/backend/api.py                    FastAPI server with Swagger
src/backend/api_keys.py               create / list / revoke API keys
src/backend/export_possession_due.py  product #1 export: projects completing in the next N days
src/backend/db.py, env.py             shared helpers (connection, schema, .env loading)
startup.sh                            build the frontend and serve it with the API on one port (local)
Dockerfile, deploy/start.sh           production image: built frontend + backend in one container
docker-compose.prod.yml               server deployment: app + Postgres on a volume
railway.json                          the same image on Railway
src/frontend/                         Svelte landing page: splash, scroll-driven map, waitlist form (Vite)
data/raw/                             every Apify run saved as JSON before loading
data/exports/                         CSVs for customers
```

## Setup

```bash
git clone https://github.com/omkarajagunde/data-driven-leads-application.git && cd data-driven-leads-application
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && chmod 600 .env   # Apify token, Postgres password, DATABASE_URL
docker compose up -d                     # Postgres on localhost:5432, pgweb on http://localhost:8081
python3 src/backend/driver.py init               # create tables, load regions.json
```

## Start everything

```bash
./startup.sh        # http://localhost:8000
```

It starts the containers, builds the frontend and serves the page and the API from one server.

| What | Where |
|---|---|
| Landing page with the map | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Database UI (pgweb) | http://localhost:8081 |

## Containers

```bash
docker compose up -d --build     # rebuild and start Postgres + pgweb (data is kept)
docker compose down              # stop them (data is kept)
```

Once the containers are up:

| What | Where |
|---|---|
| Database UI (pgweb: browse tables, run SQL) | http://localhost:8081 |
| Postgres itself | `localhost:5432`, database `data-driven-leads`, user `leads`, password in `.env` |
| API (start it with the command under "API" below) | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| API health check (no key needed) | http://localhost:8000/health |
| Landing page with the map (start it with the command under "Frontend" below) | http://localhost:5173 |

The API is not a container: it runs from the virtual environment with
`uvicorn api:app --app-dir src/backend --port 8000`.

## Deploy

The image builds the frontend and serves it with the API. On start it creates the tables, loads
`regions.json` and registers `FRONTEND_API_KEY`, so it works on an empty database. Data is
loaded by hand afterwards.

**Any server with Docker** (Postgres data lives on the `pgdata` volume):

```bash
cp .env.example .env          # set POSTGRES_PASSWORD, FRONTEND_API_KEY, APIFY_TOKEN
docker compose -f docker-compose.prod.yml up -d --build      # http://<server>:8000
docker compose -f docker-compose.prod.yml exec app python src/backend/driver.py start test
docker compose -f docker-compose.prod.yml exec app python src/backend/driver.py collect
```

**Railway**: add a Postgres service (it comes with a volume), then a service from this repo
(it uses `railway.json`). Set `DATABASE_URL` to the Postgres service's URL, plus
`FRONTEND_API_KEY` and `APIFY_TOKEN`. Load data from your laptop with `DATABASE_URL` set to
the Postgres public URL, or with `railway ssh`.

To copy your local data to Railway, turn on Postgres → Settings → Networking → TCP Proxy, then:

```bash
TARGET_DATABASE_URL="$(railway variables -s Postgres --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["DATABASE_PUBLIC_URL"])')" deploy/push_data.sh
```

It replaces only the data tables; the waitlist and API keys on Railway are left alone.

`FRONTEND_API_KEY` is any long random string (`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`).

## Database

| Table | One row per | Notes |
|---|---|---|
| `regions`, `zones`, `pincodes` | area | mirrored from `config/regions.json` on every driver run |
| `pincode_boundaries`, `zone_boundaries` | area outline | India Post outlines, simplified; zones are merged pincodes |
| `projects` | RERA project | main keys as columns, everything else in `details` (jsonb) |
| `project_snapshots` | project per day loaded | the numbers that move; feeds MoM / QoQ / YoY |
| `units` | apartment | carpet area, price, status; `size_band` is computed by the database |
| `ingest_runs` | load | input, row counts, Apify cost |
| `fx_rates` | currency | rupees per dollar used by the API |
| `api_keys` | API key | only the hash is stored |
| `waitlist` | person who joined from the landing page | name, profession, business categories, WhatsApp number |

Browse and query it at http://localhost:8081 (pgweb).

## Loading data

Runs start on Apify and keep going without you; collect them whenever you like.

```bash
python3 src/backend/driver.py start test        # ~$1-3: newest registry files, Pune only
python3 src/backend/driver.py start full        # every project in our pincodes, ~$50-60, overnight
python3 src/backend/driver.py start delta       # every two weeks: new registrations + changed projects
python3 src/backend/driver.py collect           # download finished runs and load them
python3 src/backend/driver.py runs              # what is running, what it cost
```

- **full** reads the whole registry once, in 4 parallel slices, keeping the districts our pincodes are in, with details, complaints and apartments.
- **delta** uses the actor's memory, so only new or changed projects are returned and charged. The first delta run charges every project once.
- Each command has a hard spend cap (`--max-cost`, defaults 3 / 65 / 15 dollars) that Apify enforces.
- `collect` keeps an offline copy of every run in `data/raw/` and names each Apify dataset so it does not expire.
- Bengaluru is skipped: its actor in `regions.json` is not `in-use`.

### Pincode outlines

Download "All India Pincode Boundary Geo JSON" (India Post) from data.gov.in into `data/raw/boundaries/`, then:

```bash
python3 src/backend/boundaries.py
```

It keeps only our pincodes, simplifies them and merges them into zone outlines. Pincodes without an
outline show as a small hexagon on the map.

Until then, `startup.sh` draws estimated zone shapes from pincode centres. Pincode centres are in
`config/regions.json`; new pincodes get one with:

```bash
python3 src/backend/geocode_pincodes.py      # needs GOOGLE_API_KEY in .env
```

## API

```bash
python3 src/backend/api_keys.py create "my first customer"     # prints the key once
uvicorn api:app --app-dir src/backend --port 8000
# Swagger: http://localhost:8000/docs  (Authorize -> paste the key)
```

| Zoom | Endpoint |
|---|---|
| 1 | `GET /v1/regions` |
| 2 | `GET /v1/regions/{region_id}/zones` |
| 3 | `GET /v1/regions/{region_id}/zones/{zone_id}/pincodes` |
| 4 | `GET /v1/pincodes/{pincode}` |
| 5 | `GET /v1/projects/{rera_id}`, `/snapshots`, `/units` |
| search | `GET /v1/projects?region_id=&zone_id=&pincode=&q=&schedule_status=` |

Every area returns the same `metrics` block: project count with MoM / QoQ / YoY change, units
(total / sold / booked / unsold), seven size bands with price range, price per sq ft in rupees and
dollars, schedule, legal and coverage counts.

`GET /v1/map/insights` is what the landing-page map draws, in one call: regions, zones, pincodes and
projects, each with the figures that matter at that zoom. Its quarterly trends (price QoQ / YoY,
launches per quarter) are **sample data** marked `"sample": true` until enough snapshot history exists.

## Frontend

```bash
cd src/frontend
npm install        # first time only
npm run dev        # http://localhost:5173
```

The page needs the API running. Its dev server adds `FRONTEND_API_KEY` from `.env` to every request,
so the key never reaches the browser.

The map is MapLibre on OpenFreeMap's free dark vector tiles, so it needs no map key.

## Product export

```bash
python3 src/backend/export_possession_due.py --days 120 --min-units 50
```

## Rules

- The only contact details we hold are the ones people type into the waitlist form themselves.
- Never pull or store complainant names, phones, emails, PANs (`includeComplainantNames` stays off).
- Sell project / society / site facts to businesses, not homeowner contacts.
- Per-unit price data is captcha-gated at source: use it for analysis, don't resell raw.
