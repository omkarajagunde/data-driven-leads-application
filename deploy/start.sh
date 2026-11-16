#!/bin/sh
# Container start: prepare the database (idempotent), then serve the API and the landing page.
set -e
python src/backend/driver.py init                 # tables, regions.json, the frontend's API key
python src/backend/boundaries.py --estimate       # zone shapes, until real pincode outlines are loaded
# Behind Railway's (or any) proxy every request arrives from the proxy's address. Trusting the
# forwarded header gives each visitor their own rate limit. Only the proxy can reach this port,
# so trusting it is safe; set FORWARDED_ALLOW_IPS to the proxy's address to narrow it.
exec uvicorn api:app --app-dir src/backend --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}"
