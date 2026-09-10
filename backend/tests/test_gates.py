"""The quality gates must be able to fail.

Both halves of #1416: a CI step that backgrounds its gates and then bare-`wait`s always exits 0,
and a gate function whose first failing command is masked by a later passing one.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GATES = REPO_ROOT / "scripts" / "gates.sh"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

BACKGROUNDED = re.compile(r"(?<![&>])&(?![&>])")
BARE_WAIT = re.compile(r"(?:^|[;&|]|\bthen\b|\bdo\b)\s*wait\s*(?:$|[;&|\n])", re.MULTILINE)


def _ruff_stub(tmp_path: Path, failing_subcommand: str) -> Path:
    """A `uv` on PATH whose `uv run ruff <subcommand>` fails only for the given subcommand.

    The gate invokes tools through `uv run`, which puts the real venv first on PATH, so a bare
    `ruff` stub would be shadowed; stubbing `uv` itself is the only seam.
    """
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "uv"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'[ "$1" = run ] && [ "$2" = ruff ] && [ "$3" = "{failing_subcommand}" ] && exit 1\n'
        "exit 0\n"
    )
    stub.chmod(0o755)
    return stub_dir


def _run_lint_gate(stub_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(GATES), "lint"],
        cwd=REPO_ROOT,
        env={**os.environ, "PATH": f"{stub_dir}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("failing_subcommand", ["check", "format"])
def test_lint_gate_fails_when_any_ruff_invocation_fails(tmp_path, failing_subcommand):
    result = _run_lint_gate(_ruff_stub(tmp_path, failing_subcommand))

    assert result.returncode != 0, f"ruff {failing_subcommand} failed but the gate reported {result.stdout}"
    assert "FAILED: lint" in result.stdout


def test_lint_gate_passes_when_ruff_succeeds(tmp_path):
    result = _run_lint_gate(_ruff_stub(tmp_path, failing_subcommand="never-a-subcommand"))

    assert result.returncode == 0, result.stderr
    assert "PASSED: lint" in result.stdout


def _workflow_run_steps() -> list[tuple[str, str]]:
    steps = []
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        for job in yaml.safe_load(workflow.read_text())["jobs"].values():
            for step in job.get("steps", []):
                if "run" in step:
                    steps.append((f"{workflow.name}:{step.get('name', 'unnamed')}", step["run"]))
    return steps


def test_there_are_workflow_steps_to_scan():
    assert len(_workflow_run_steps()) >= 5


def test_no_workflow_step_backgrounds_a_command():
    """A backgrounded gate reports through `wait`, which discards its exit code."""
    offenders = [name for name, run in _workflow_run_steps() if BACKGROUNDED.search(run) or BARE_WAIT.search(run)]
    assert offenders == [], f"these steps cannot fail on a backgrounded command: {offenders}"
