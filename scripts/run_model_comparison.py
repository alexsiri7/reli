#!/usr/bin/env python3
"""CLI script to run model comparison evals and produce a report.

Runs the reasoning and/or context agent golden datasets across multiple
models, then outputs a markdown table and JSON report identifying the
cheapest model per stage that meets quality thresholds.

Requirements:
    - REQUESTY_API_KEY or GOOGLE_API_KEY must be set
    - Run from the project root (same as pytest)

Usage:
    # Compare all stages (reasoning + context)
    python scripts/run_model_comparison.py

    # Compare only reasoning stage
    python scripts/run_model_comparison.py --stage reasoning

    # Increase runs per case for tighter variance estimate
    python scripts/run_model_comparison.py --runs 5

    # Write reports to a specific directory
    python scripts/run_model_comparison.py --out-dir eval/reports

    # JSON output only
    python scripts/run_model_comparison.py --output json
"""

import asyncio
import sys
from pathlib import Path

# Ensure the project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval._comparison_runner import _main  # noqa: E402

if __name__ == "__main__":
    asyncio.run(_main())
