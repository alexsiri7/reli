# Stage 1: Build frontend
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --legacy-peer-deps && npm rebuild rolldown
COPY frontend/ ./
RUN npm run build

# Stage 2: Production image
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
ENV OAUTHLIB_RELAX_TOKEN_SCOPE=1

# Copy config
COPY config.yaml ./config.yaml
COPY alembic.ini ./alembic.ini

# Copy backend and prompts
COPY backend/ ./backend/
COPY prompts/ ./prompts/

# Copy frontend build from stage 1
COPY --from=frontend-build /app/frontend/dist/ ./frontend/dist/

# Create data & chroma_db directories with correct ownership
# chroma_db: defensive — chromadb was removed in the pgvector migration but
# cached Docker layers or transitive deps could still try to initialise it.
RUN mkdir -p /app/data /app/backend/chroma_db && \
    chown reli:reli /app/data /app/backend/chroma_db

# Entrypoint fixes bind-mount permissions then drops to non-root
COPY --chmod=755 <<'ENTRY' /app/entrypoint.sh
#!/bin/sh
# Fix ownership of bind-mounted data dir (runs as root initially)
chown -R reli:reli /app/data 2>/dev/null || true
# Ensure chroma_db dir is writable (defensive — chromadb removed in pgvector migration)
mkdir -p /app/backend/chroma_db && chown reli:reli /app/backend/chroma_db 2>/dev/null || true
exec gosu reli "$@"
ENTRY

EXPOSE 8000

# 60 s gives Railway cold boots (Alembic migrations + MCP startup) time to complete
# before Docker begins probing. Total time-to-unhealthy on genuine crash: ≤150 s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",\"8000\")}/healthz')" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
