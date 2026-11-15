# The web view is built here and copied into the runtime image, so one container serves the API and
# the frontend — docs/vision.md §4.4. Playwright's browsers are never needed in an image that only
# serves the bundle, and downloading them would add hundreds of megabytes to the build.
FROM node:22-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee AS frontend-build
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# uv is its own stage rather than an inline `COPY --from=<image>` so Dependabot's docker updates
# see it and move it.
FROM ghcr.io/astral-sh/uv:0.11.13@sha256:841c8e6fe30a8b07b4478d12d0c608cba6de66102d29d65d1cc423af86051563 AS uv

# Every base is pinned by digest, so a repointed tag cannot change the image unseen (#1814). The tag
# stays beside it because Dependabot's docker updates read it and move the digest to each patched
# 3.12-slim — that is how security patches land (#1203).
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
WORKDIR /app

# Create non-root user
RUN groupadd --gid 1000 reli && \
    useradd --uid 1000 --gid reli --shell /bin/false reli

# Install uv (pinned version for reproducibility)
COPY --from=uv /uv /usr/local/bin/uv

# Install Python dependencies from lock file
# psycopg2 (source) requires libpq-dev gcc libc6-dev at build time; libpq5 at runtime
COPY pyproject.toml uv.lock ./
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev gcc libc6-dev && \
    UV_SYSTEM_PYTHON=1 uv sync --frozen --no-dev && \
    apt-get purge -y libpq-dev gcc libc6-dev && \
    apt-get install -y --no-install-recommends libpq5 && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Add the virtualenv created by uv sync to PATH so uvicorn and python
# resolve to the venv's binaries rather than the (empty) system install.
ENV PATH="/app/.venv/bin:$PATH"

COPY alembic.ini ./alembic.ini
COPY backend/ ./backend/
# get_scheduled_instructions reads prompts/scheduled/ at call time (#1506).
COPY prompts/ ./prompts/
COPY --from=frontend-build /frontend/dist ./frontend/dist

# Set before HEALTHCHECK and CMD so the server and every probe run as reli from container start.
USER reli

EXPOSE 8000

# 60 s gives Railway cold boots (Alembic migrations) time to complete before
# Docker begins probing. Total time-to-unhealthy on genuine crash: ≤150 s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",\"8000\")}/healthz')" || exit 1

CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
