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
set -Eeuo pipefail

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
