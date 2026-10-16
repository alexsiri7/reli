"""A deploy turns the pipeline red unless Railway actually runs the image.

#1660: CI's prune step deleted the platform manifest an image index pointed at, Railway failed to
pull the tag at ``CREATE_CONTAINER``, the previous container kept answering ``/healthz``, and the
pipeline went green. ``scripts/deploy-railway.sh`` is run here against a stub ``curl`` that plays
both GHCR and Railway, and its log is what reached them.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY = REPO_ROOT / "scripts" / "deploy-railway.sh"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

IMAGE = "ghcr.io/alexsiri7/reli:abc123"
CHILDREN = ("sha256:aaaa", "sha256:bbbb")

STUB_CURL = """#!/usr/bin/env bash
args="$*"
printf '%s\\n' "${args//$'\\n'/ }" >> "$STUB/log"
case "$*" in
  *ghcr.io/token*) echo '{"token":"t"}' ;;
  */manifests/abc123*)
    [ -e "$STUB/no-tag" ] && exit 22
    echo '{"manifests":[{"digest":"sha256:aaaa"},{"digest":"sha256:bbbb"}]}' ;;
  */manifests/sha256:*)
    url=${!#}
    digest=${url##*/manifests/}
    grep -qx "$digest" "$STUB/missing" 2>/dev/null && exit 22
    exit 0 ;;
  *serviceInstanceUpdate*) echo '{"data":{"serviceInstanceUpdate":true}}' ;;
  *serviceInstanceDeployV2*) echo '{"data":{"serviceInstanceDeployV2":"dep-1"}}' ;;
  *'deployment(id'*)
    n=$(( $(cat "$STUB/polls" 2>/dev/null || echo 0) + 1 ))
    echo "$n" > "$STUB/polls"
    echo "{\\"data\\":{\\"deployment\\":{\\"status\\":\\"$(sed -n "${n}p" "$STUB/statuses")\\"}}}" ;;
  *) exit 1 ;;
esac
"""

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="the deploy script needs jq")


def _deploy(
    tmp_path: Path, statuses: list[str], *, missing: tuple[str, ...] = (), no_tag: bool = False
) -> tuple[subprocess.CompletedProcess, list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text(STUB_CURL)
    (bin_dir / "curl").chmod(0o755)
    (tmp_path / "statuses").write_text("".join(f"{s}\n" for s in statuses))
    (tmp_path / "missing").write_text("".join(f"{d}\n" for d in missing))
    if no_tag:
        (tmp_path / "no-tag").touch()
    result = subprocess.run(
        ["bash", str(DEPLOY), IMAGE],
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "STUB": str(tmp_path),
            "RAILWAY_TOKEN": "token",
            "SERVICE_ID": "svc",
            "ENV_ID": "env",
            "RAILWAY_POLL_INTERVAL": "0",
            "RAILWAY_POLL_ATTEMPTS": "5",
        },
        capture_output=True,
        text=True,
    )
    log = (tmp_path / "log").read_text().splitlines() if (tmp_path / "log").exists() else []
    return result, log


def _reached_railway(log: list[str]) -> bool:
    return any("backboard.railway.app" in line for line in log)


def test_a_tag_that_does_not_exist_is_never_deployed(tmp_path):
    result, log = _deploy(tmp_path, ["SUCCESS"], no_tag=True)

    assert result.returncode != 0
    assert f"::error::Image {IMAGE} does not exist" in result.stdout
    assert not _reached_railway(log)


def test_an_index_whose_image_manifest_was_deleted_is_never_deployed(tmp_path):
    """The #1660 shape: the tag resolves, but the platform image it indexes is gone."""
    result, log = _deploy(tmp_path, ["SUCCESS"], missing=(CHILDREN[0],))

    assert result.returncode != 0
    assert f"references {CHILDREN[0]}" in result.stdout
    assert not _reached_railway(log)


@pytest.mark.parametrize("status", ["FAILED", "CRASHED", "REMOVED"])
def test_a_failed_railway_deployment_fails_the_job(tmp_path, status):
    result, _ = _deploy(tmp_path, ["DEPLOYING", status])

    assert result.returncode != 0
    assert f"::error::Railway deployment dep-1 ended {status}" in result.stdout


def test_a_deployment_that_goes_live_passes(tmp_path):
    result, log = _deploy(tmp_path, ["QUEUED", "DEPLOYING", "SUCCESS"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Railway deployment dep-1 is live" in result.stdout
    railway = [line for line in log if "backboard.railway.app" in line]
    assert "serviceInstanceUpdate" in railway[0]
    assert IMAGE in railway[0]
    assert "serviceInstanceDeployV2" in railway[1]
    assert len(railway) == 2 + 3


def test_a_deployment_that_never_settles_fails(tmp_path):
    result, _ = _deploy(tmp_path, ["DEPLOYING"] * 5)

    assert result.returncode != 0
    assert "::error::Railway deployment dep-1 did not finish" in result.stdout


def test_ci_never_deletes_published_images():
    """#1660: ``delete-package-versions`` counts an index's child manifests as versions of their own,
    so an unchanged image's platform manifest — old-dated, re-referenced by the new index — was
    deleted as "old", leaving the freshly pushed tag unpullable."""
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    offenders = [
        f"{name}:{step.get('name')}"
        for name, job in ci["jobs"].items()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("actions/delete-package-versions")
    ]
    assert offenders == []


def test_both_deploy_jobs_go_through_the_checked_deploy():
    pipeline = yaml.safe_load((WORKFLOWS / "staging-pipeline.yml").read_text())
    steps = {step.get("name"): step for job in pipeline["jobs"].values() for step in job["steps"]}

    for name in ("Deploy staging image to Railway", "Deploy production image to Railway"):
        assert "./scripts/deploy-railway.sh" in steps[name]["run"]
    assert not any("serviceInstanceDeploy(" in step.get("run", "") for step in steps.values()), (
        "serviceInstanceDeploy returns no deployment id, so nothing can wait on its outcome"
    )
