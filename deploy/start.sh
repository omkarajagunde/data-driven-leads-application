#!/bin/sh
# Container start: prepare the database (idempotent), then serve the API and the landing page.
set -e
python src/backend/driver.py init                 # tables, regions.json, the frontend's API key
python src/backend/boundaries.py --estimate       # zone shapes, until real pincode outlines are loaded
exec uvicorn api:app --app-dir src/backend --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers
