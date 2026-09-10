#!/usr/bin/env bash
# gates.sh — Single source of truth for all quality gates.
# Called by: polecats (pre-verify), refinery (fallback), CI (GitHub Actions).
#
# Usage:
#   ./scripts/gates.sh [STAGE...]
#
# Stages: setup, lint, typecheck, test, build, frontend
# No args = run every stage but `frontend`, which needs node and a browser.
# Examples:
#   ./scripts/gates.sh              # Run setup, lint, typecheck, test and build
#   ./scripts/gates.sh lint test    # Run only lint and test
#   ./scripts/gates.sh frontend     # Run the web view's gates (node + Playwright)
set -Eeuo pipefail

cd "$(git rev-parse --show-toplevel)"

run_setup() {
    echo "=== Setup ==="
    uv sync --locked
}

# Tools live in the uv-managed venv created by `setup`. CI never activates it, so invoke them
# through `uv run` (like the test stage) instead of relying on them being on PATH.
run_lint() {
    echo "=== Lint ==="
    uv run ruff check backend/
    uv run ruff format --check backend/
}

run_typecheck() {
    echo "=== Typecheck ==="
    uv run mypy backend/
}

# Needs a Docker daemon: the suite starts a throwaway Postgres via testcontainers.
# Set RELI_TEST_DATABASE_URL to run against an existing database instead.
run_test() {
    echo "=== Test ==="
    uv run pytest backend/tests/ -x --tb=short --cov=backend --cov-fail-under=70
}

run_build() {
    echo "=== Build (Docker) ==="
    docker build -t reli:gate-check .
}

# Deliberately absent from the no-arg default: it needs node and a browser, and making those a hard
# dependency of every local gate run is a wider blast radius than the web view earns. CI runs it as
# its own job, inside the Playwright container the snapshots were generated in.
run_frontend() {
    echo "=== Frontend ==="
    (
        cd frontend
        npm ci
        npm run lint
        npm run typecheck
        npm run build
        npx playwright test
    )
}

# If no args, run all stages
STAGES=("${@:-setup lint typecheck test build}")
if [ $# -eq 0 ]; then
    STAGES=(setup lint typecheck test build)
fi

# Report the failure from an ERR trap rather than `if ! run_${stage}`: calling a function in a
# condition context disables errexit inside it, so a failing first command (ruff check) would be
# masked by a passing second one (ruff format --check).
trap 'echo "FAILED: ${stage:-}"; echo "=== Gates FAILED ==="; exit 1' ERR

for stage in "${STAGES[@]}"; do
    "run_${stage}"
    echo "PASSED: ${stage}"
    echo ""
done

echo "=== All gates passed ==="
