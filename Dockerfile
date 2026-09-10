# The web view is built here and copied into the runtime image, so one container serves the API and
# the frontend — docs/vision.md §4.4. Playwright's browsers are never needed in an image that only
# serves the bundle, and downloading them would add hundreds of megabytes to the build.
FROM node:22-slim AS frontend-build
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Use floating minor tag so security patches land on each rebuild.
# Run `docker compose build --pull` (or ensure CI uses --pull) to guarantee
# the latest python:3.12.x base is fetched rather than served from cache.
FROM python:3.12-slim
WORKDIR /app

# Create non-root user
RUN groupadd --gid 1000 reli && \
    useradd --uid 1000 --gid reli --shell /bin/false reli

# Install uv (pinned version for reproducibility)
COPY --from=ghcr.io/astral-sh/uv:0.11.13 /uv /usr/local/bin/uv

# Install Python dependencies from lock file
# psycopg2 (source) requires libpq-dev gcc libc6-dev at build time; libpq5 at runtime
COPY pyproject.toml uv.lock ./
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev gcc libc6-dev && \
    UV_SYSTEM_PYTHON=1 uv sync --frozen --no-dev && \
    apt-get purge -y libpq-dev gcc libc6-dev && \
    apt-get install -y --no-install-recommends libpq5 gosu && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Add the virtualenv created by uv sync to PATH so uvicorn and python
# resolve to the venv's binaries rather than the (empty) system install.
ENV PATH="/app/.venv/bin:$PATH"

COPY alembic.ini ./alembic.ini
COPY backend/ ./backend/
COPY --from=frontend-build /frontend/dist ./frontend/dist

# Entrypoint drops to non-root
COPY --chmod=755 <<'ENTRY' /app/entrypoint.sh
#!/bin/sh
exec gosu reli "$@"
ENTRY

EXPOSE 8000

# 60 s gives Railway cold boots (Alembic migrations) time to complete before
# Docker begins probing. Total time-to-unhealthy on genuine crash: ≤150 s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",\"8000\")}/healthz')" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
