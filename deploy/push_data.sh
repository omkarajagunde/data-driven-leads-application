#!/usr/bin/env bash
# Copy the data tables from the local Postgres (docker compose) to another Postgres, e.g. Railway.
#
#   TARGET_DATABASE_URL='postgresql://…' deploy/push_data.sh
#
# On Railway, TARGET_DATABASE_URL is the Postgres service's DATABASE_PUBLIC_URL (turn on
# Settings → Networking → TCP Proxy first). The target's copies of these tables are replaced in
# one transaction: if anything fails, the target is left as it was.
#
# Copied:   projects, project_snapshots, units, site_signals, pincode_boundaries, zone_boundaries, ingest_runs
# Left alone on the target: waitlist (real sign-ups), api_keys, regions / zones / pincodes
# (the app rebuilds those from config/regions.json on every start), fx_rates.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${TARGET_DATABASE_URL:?set TARGET_DATABASE_URL to the target database URL}"
LOCAL="${LOCAL_CONTAINER:-data-driven-leads-postgres-1}"
TABLES=(projects project_snapshots units site_signals pincode_boundaries zone_boundaries ingest_runs)

# psql and pg_dump come from the local Postgres container, so nothing needs installing.
# (only the load itself reads standard input; the queries must not, or they would eat the y/N answer)
target() { docker exec "$LOCAL" psql "$TARGET_DATABASE_URL" -X -v ON_ERROR_STOP=1 -q "$@"; }
target_load() { docker exec -i "$LOCAL" psql "$TARGET_DATABASE_URL" -X -v ON_ERROR_STOP=1 -q; }
local_q() { docker exec "$LOCAL" psql -U leads -d data-driven-leads -X -tA "$@"; }
counts="select 'projects', count(*) from projects union all select 'apartments', count(*) from units
        union all select 'snapshots', count(*) from project_snapshots union all select 'waitlist', count(*) from waitlist"

echo "==> target: $(target -tAc "select current_database() || ' on ' || split_part(version(), ' ', 2)")"
if ! target -tAc "select 1 from projects limit 1" >/dev/null 2>&1; then
  echo "The target has no tables yet. Deploy the app once (it creates them on start), then run this again." >&2
  exit 1
fi
echo "==> target before:"; target -tAc "$counts" | sed 's/|/: /; s/^/    /'
echo "==> local:";         local_q -c "$counts" | sed 's/|/: /; s/^/    /'

read -r -p "Replace the target's data tables with the local ones? [y/N] " ok
[ "$ok" = "y" ] || [ "$ok" = "Y" ] || { echo "Nothing changed."; exit 0; }

dump_args=(); for t in "${TABLES[@]}"; do dump_args+=(-t "$t"); done
echo "==> copying (one transaction)"
{
  echo "BEGIN;"
  echo "TRUNCATE $(IFS=,; echo "${TABLES[*]}");"
  docker exec "$LOCAL" pg_dump -U leads -d data-driven-leads --data-only --no-owner --no-privileges "${dump_args[@]}"
  echo "COMMIT;"
} | target_load >/dev/null   # errors still show; the setval noise does not

echo "==> target after:"; target -tAc "$counts" | sed 's/|/: /; s/^/    /'
echo "Done. The site's cached summaries refresh within 10 minutes (or restart the app service)."
