# Stage 1: Build frontend
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --legacy-peer-deps && npm rebuild rolldown
COPY frontend/ ./
RUN npm run build

# Stage 2: Production image
FROM python:3.12.8-slim
WORKDIR /app

# Create non-root user
RUN groupadd --gid 1000 reli && \
    useradd --uid 1000 --gid reli --shell /bin/false reli

# Install Python dependencies
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

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

RUN apt-get update && apt-get install -y --no-install-recommends gosu && rm -rf /var/lib/apt/lists/*

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
