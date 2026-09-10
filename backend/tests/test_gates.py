"""The quality gates must be able to fail — and to pass.

Both halves of #1416: a CI step that backgrounds its gates and then bare-`wait`s always exits 0,
and a gate function whose first failing command is masked by a later passing one. Plus the
opposite failure: a gate that cannot reach its tools fails every build without ever running them.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GATES = REPO_ROOT / "scripts" / "gates.sh"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

BACKGROUNDED = re.compile(r"(?<![&>])&(?![&>])")
BARE_WAIT = re.compile(r"(?:^|[;&|]|\bthen\b|\bdo\b)\s*wait\s*(?:$|[;&|\n])", re.MULTILINE)

# What `gates.sh` needs on PATH before it reaches a stage. Every venv tool goes through
# `uv run`, because CI never activates the venv.
SANDBOX_TOOLS = ("bash", "git")


def _sandbox_bin(tmp_path: Path, failing_invocation: str) -> Path:
    """A PATH holding only the gate's genuine externals plus a stub `uv`.

    `ruff` and `mypy` are unreachable here, exactly as on CI's PATH, so a gate that stopped routing
    them through `uv run` would fail the passing case with command-not-found. The stub fails any
    `uv` call whose arguments start with `failing_invocation`.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in SANDBOX_TOOLS:
        real = shutil.which(tool)
        assert real, f"{tool} is not installed; the gate needs it"
        (bin_dir / tool).symlink_to(real)
    for venv_tool in ("ruff", "mypy"):
        assert shutil.which(venv_tool, path=str(bin_dir)) is None
    stub = bin_dir / "uv"
    stub.write_text(f'#!/usr/bin/env bash\ncase "$*" in "{failing_invocation}"*) exit 1 ;; esac\nexit 0\n')
    stub.chmod(0o755)
    return bin_dir


def _run_gate(bin_dir: Path, stage: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(bin_dir / "bash"), str(GATES), stage],
        cwd=REPO_ROOT,
        env={**os.environ, "PATH": str(bin_dir)},
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("stage", "failing_invocation"),
    [
        ("lint", "run ruff check"),
        ("lint", "run ruff format"),
        ("typecheck", "run mypy"),
    ],
)
def test_gate_fails_when_any_tool_invocation_fails(tmp_path, stage, failing_invocation):
    result = _run_gate(_sandbox_bin(tmp_path, failing_invocation), stage)

    assert result.returncode != 0, f"`uv {failing_invocation}` failed but the gate reported {result.stdout}"
    assert f"FAILED: {stage}" in result.stdout


@pytest.mark.parametrize("stage", ["lint", "typecheck"])
def test_gate_passes_when_its_tools_succeed(tmp_path, stage):
    """Guards the other direction: a gate that cannot find its tools fails every build."""
    result = _run_gate(_sandbox_bin(tmp_path, failing_invocation="never-an-invocation"), stage)

    assert result.returncode == 0, result.stderr
    assert f"PASSED: {stage}" in result.stdout


def _workflow_run_steps(directory: Path = WORKFLOWS) -> list[tuple[str, str]]:
    steps = []
    workflows = (p for p in directory.iterdir() if p.suffix in (".yml", ".yaml"))
    for workflow in sorted(workflows):
        for job in yaml.safe_load(workflow.read_text())["jobs"].values():
            for step in job.get("steps", []):
                if "run" in step:
                    steps.append((f"{workflow.name}:{step.get('name', 'unnamed')}", step["run"]))
    return steps


def _backgrounding_steps(steps: list[tuple[str, str]]) -> list[str]:
    return [name for name, run in steps if BACKGROUNDED.search(run) or BARE_WAIT.search(run)]


def test_there_are_workflow_steps_to_scan():
    assert len(_workflow_run_steps()) >= 5


def test_no_workflow_step_backgrounds_a_command():
    """A backgrounded gate reports through `wait`, which discards its exit code."""
    offenders = _backgrounding_steps(_workflow_run_steps())
    assert offenders == [], f"these steps cannot fail on a backgrounded command: {offenders}"


@pytest.mark.parametrize("extension", [".yml", ".yaml"])
def test_the_scan_covers_both_workflow_extensions(tmp_path, extension):
    """GitHub Actions runs `.yaml` workflows too; a scan that skips them protects nothing."""
    (tmp_path / f"deploy{extension}").write_text(
        "jobs:\n"
        "  gate:\n"
        "    steps:\n"
        "      - name: Lint & Typecheck\n"
        "        run: ./scripts/gates.sh lint & ./scripts/gates.sh typecheck & wait\n"
    )

    assert _backgrounding_steps(_workflow_run_steps(tmp_path)) == [f"deploy{extension}:Lint & Typecheck"]
