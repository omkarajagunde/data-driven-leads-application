#!/usr/bin/env bash
# Build the landing page and serve it, together with the API, from one FastAPI server.
#   ./startup.sh            -> http://localhost:8000
#   PORT=9000 ./startup.sh  -> another port
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"

echo "==> starting Postgres and pgweb"
docker compose up -d --wait

if [ ! -x .venv/bin/uvicorn ]; then
  echo "==> creating the Python environment"
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

echo "==> preparing the database"
.venv/bin/python src/backend/driver.py init
.venv/bin/python src/backend/boundaries.py --estimate   # zone shapes, until real pincode outlines are loaded

echo "==> building the frontend"
(
  cd src/frontend
  [ -d node_modules ] || npm install --no-audit --no-fund
  npm run build
)

# Free the port first, so a server left running from last time does not block this one.
if pids=$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null) && [ -n "$pids" ]; then
  echo "==> stopping what is already on port ${PORT} (pid $(echo $pids | tr '\n' ' '))"
  kill $pids 2>/dev/null || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do lsof -ti "tcp:${PORT}" -sTCP:LISTEN >/dev/null 2>&1 || break; sleep 0.5; done
  if pids=$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null) && [ -n "$pids" ]; then kill -9 $pids 2>/dev/null || true; sleep 0.5; fi
fi

echo "==> serving on http://localhost:${PORT}  (API docs: /docs, database UI: http://localhost:8081)"
exec .venv/bin/uvicorn api:app --app-dir src/backend --host 127.0.0.1 --port "$PORT"
