# One image: the FastAPI backend serving the built Svelte landing page.
# Postgres runs separately (docker-compose.prod.yml, or a managed Postgres such as Railway's).

# ---- frontend build
FROM node:22-slim AS web
WORKDIR /app/src/frontend
COPY src/frontend/package.json src/frontend/package-lock.json src/frontend/.npmrc ./
RUN npm ci --no-audit --no-fund
COPY src/frontend/ ./
RUN npm run build

# ---- backend
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY config ./config
COPY db ./db
COPY src/backend ./src/backend
COPY --from=web /app/src/frontend/dist ./src/frontend/dist
COPY deploy/start.sh ./deploy/start.sh
EXPOSE 8000
CMD ["sh", "deploy/start.sh"]
