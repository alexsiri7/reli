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
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"

BACKGROUNDED = re.compile(r"(?<![&>])&(?![&>])")
UV_SYNC = re.compile(r"uv sync[^\n&|;]*")
BARE_WAIT = re.compile(r"(?:^|[;&|]|\bthen\b|\bdo\b)\s*wait\s*(?:$|[;&|\n])", re.MULTILINE)
# An ``/api`` path as a URL, not as a repository path: ``backend/api.py`` is prose a workflow may
# name, and ``api.github.com`` has no leading slash.
API_ROUTE = re.compile(r"""/api(?:/|(?=["'\s]|$))""")
# ``ntfy.sh`` used as a URL without ``https://`` in front of it. curl guesses ``http`` for a bare
# host, and the topic name is the channel's whole credential.
PLAINTEXT_NTFY = re.compile(r"""(?<!https://)\bntfy\.sh/""")

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


def _plaintext_ntfy_steps(steps: list[tuple[str, str]]) -> list[str]:
    return [name for name, run in steps if PLAINTEXT_NTFY.search(run)]


def test_no_workflow_step_posts_to_ntfy_over_plaintext():
    """#1541: a scheme-less ``ntfy.sh/$NTFY_TOPIC`` sends the topic — the channel's only secret — in the clear."""
    offenders = _plaintext_ntfy_steps(_workflow_run_steps())
    assert offenders == [], f"these steps reach ntfy.sh without https://: {offenders}"


def _graph_reading_workflows(directory: Path = WORKFLOWS) -> list[str]:
    """Workflows naming an ``/api`` route anywhere — in a ``run:`` script or in an ``env:`` URL."""
    workflows = (p for p in directory.iterdir() if p.suffix in (".yml", ".yaml"))
    return [w.name for w in sorted(workflows) if API_ROUTE.search(w.read_text())]


def test_no_workflow_reads_the_graph_into_github_actions():
    """#1484: this repository is public, so no runner may hold the owner's Things."""
    offenders = _graph_reading_workflows()
    assert offenders == [], f"these workflows read an /api route: {offenders}"


def _jobs_on_default_token_grants(directory: Path = WORKFLOWS) -> list[str]:
    """Jobs whose ``GITHUB_TOKEN`` scope is neither set at the top of the workflow nor on the job."""
    workflows = (p for p in directory.iterdir() if p.suffix in (".yml", ".yaml"))
    offenders: list[str] = []
    for workflow in sorted(workflows):
        document = yaml.safe_load(workflow.read_text())
        if "permissions" in document:
            continue
        offenders.extend(
            f"{workflow.name}:{name}" for name, job in document["jobs"].items() if "permissions" not in job
        )
    return offenders


def test_every_workflow_job_declares_its_token_permissions():
    """#1539: a job without a ``permissions`` block runs on the repository default, not a chosen minimum."""
    offenders = _jobs_on_default_token_grants()
    assert offenders == [], f"these jobs run on the default GITHUB_TOKEN grants: {offenders}"


def test_the_permissions_scan_sees_a_job_left_on_the_default_grants(tmp_path):
    """A top-level block covers every job in its workflow; without one, each job must declare its own."""
    (tmp_path / "covered.yml").write_text("permissions:\n  contents: read\njobs:\n  x:\n    steps: []\n")
    (tmp_path / "bare.yml").write_text(
        "jobs:\n  x:\n    permissions:\n      contents: read\n    steps: []\n  y:\n    steps: []\n"
    )
    assert _jobs_on_default_token_grants(tmp_path) == ["bare.yml:y"]


def test_ci_grants_its_default_token_nothing_beyond_read():
    """The scan above accepts any top-level block; this holds ci.yml's to the read-only grant #1539 chose."""
    document = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    assert document["permissions"] == {"contents": "read"}


def test_the_graph_read_scan_tells_a_deploy_route_from_a_repository_path(tmp_path):
    """Without the negatives the scan would fail on any workflow that merely names ``backend/api.py``."""
    (tmp_path / "reads.yml").write_text('jobs:\n  x:\n    steps:\n      - run: curl "$URL/api/things"\n')
    (tmp_path / "innocent.yml").write_text(
        "jobs:\n  x:\n    steps:\n"
        "      - run: gh api https://api.github.com/repos/alexsiri7/reli\n"
        "      - run: ruff check backend/api.py\n"
        '      - run: curl "$URL/healthz"\n'
    )

    assert _graph_reading_workflows(tmp_path) == ["reads.yml"]


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


def _uv_sync_invocations() -> list[tuple[str, str]]:
    """Every dependency install CI performs — the workflow steps plus the gate script they call."""
    sources = _workflow_run_steps() + [(GATES.name, GATES.read_text())]
    return [(name, match.group().strip()) for name, script in sources for match in UV_SYNC.finditer(script)]


def test_there_are_installs_to_scan():
    assert len(_uv_sync_invocations()) >= 4


def test_every_ci_install_rejects_a_lockfile_that_pyproject_has_outgrown():
    """#1432: `--frozen` installs `uv.lock` whatever `pyproject.toml` now says, so a dependabot
    bump that raises a constraint without relocking ships the old version green."""
    offenders = [f"{name}: {command}" for name, command in _uv_sync_invocations() if "--locked" not in command]
    assert offenders == [], f"these installs accept a stale lockfile: {offenders}"


def test_dependabot_bumps_the_lockfile_alongside_pyproject():
    """The `pip` ecosystem edits `pyproject.toml` alone (#1422, #1427); `uv` relocks with it, so the
    installs above stay green through a bump instead of failing on drift dependabot cannot fix."""
    ecosystems = {update["package-ecosystem"] for update in yaml.safe_load(DEPENDABOT.read_text())["updates"]}

    assert "uv" in ecosystems
    assert "pip" not in ecosystems, "the pip ecosystem raises pyproject-only bumps that leave uv.lock behind"


def test_the_frontend_lockfile_is_updated_and_scanned_like_the_backend_one():
    """#1540: `frontend/package-lock.json` gets the same dependabot bumps and vulnerability scan
    `uv.lock` does, rather than being patched by hand when someone happens to look."""
    updates = yaml.safe_load(DEPENDABOT.read_text())["updates"]
    assert {u["directory"] for u in updates if u["package-ecosystem"] == "npm"} == {"/frontend"}

    scan = yaml.safe_load((WORKFLOWS / "dependency-scan.yml").read_text())
    # YAML 1.1 reads a bare ``on:`` key as the boolean True.
    for event in ("push", "pull_request"):
        assert "frontend/package-lock.json" in scan[True][event]["paths"], event
    audit_steps = [step for job in scan["jobs"].values() for step in job["steps"] if "npm audit" in step.get("run", "")]
    assert [step.get("working-directory") for step in audit_steps] == ["frontend"]
