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
    cd frontend && npm ci --legacy-peer-deps && cd ..
    pip install -q -r backend/requirements.txt 2>/dev/null || true
}

run_lint() {
    echo "=== Lint (backend) ==="
    ruff check backend/
    ruff format --check backend/

    echo "=== Lint (frontend) ==="
    cd frontend && npx eslint . && cd ..
}

run_typecheck() {
    echo "=== Typecheck (frontend) ==="
    cd frontend && npx tsc -b && cd ..

    echo "=== Typecheck (backend) ==="
    mypy backend/

    echo "=== Generated types fresh check ==="
    cd frontend && npm run check:types-fresh && cd ..
}

run_test() {
    local failed=0

    echo "=== Test (frontend) ==="
    if ! (cd frontend && npx vitest run); then
        echo "FAILED: frontend tests"
        failed=1
    fi

    echo "=== Test (backend) ==="
    if ! python3 -m pytest backend/tests/ -x --tb=short --cov=backend --cov-fail-under=70; then
        echo "FAILED: backend tests"
        failed=1
    fi

    return $failed
}

run_build() {
    echo "=== Build (Docker) ==="
    docker build -t reli:gate-check .
}

run_screenshots() {
    echo "=== Screenshots (visual regression) ==="
    cd frontend && npm run test:screenshots && cd ..
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
