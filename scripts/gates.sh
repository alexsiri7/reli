#!/usr/bin/env bash
# gates.sh — Single source of truth for all quality gates.
# Called by: polecats (pre-verify), refinery (fallback), CI (GitHub Actions).
#
# Usage:
#   ./scripts/gates.sh [STAGE...]
#
# Stages: setup, lint, typecheck, test, build
# No args = run all stages in order.
# Examples:
#   ./scripts/gates.sh              # Run everything
#   ./scripts/gates.sh lint test    # Run only lint and test
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

run_setup() {
    echo "=== Setup ==="
    uv sync --frozen
}

run_lint() {
    echo "=== Lint ==="
    ruff check backend/
    ruff format --check backend/
}

run_typecheck() {
    echo "=== Typecheck ==="
    mypy backend/
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

# If no args, run all stages
STAGES=("${@:-setup lint typecheck test build}")
if [ $# -eq 0 ]; then
    STAGES=(setup lint typecheck test build)
fi

FAILED=0
for stage in "${STAGES[@]}"; do
    if ! "run_${stage}"; then
        echo "FAILED: ${stage}"
        FAILED=1
        break
    fi
    echo "PASSED: ${stage}"
    echo ""
done

if [ $FAILED -eq 0 ]; then
    echo "=== All gates passed ==="
else
    echo "=== Gates FAILED ==="
    exit 1
fi
