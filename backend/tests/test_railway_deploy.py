"""The deploy must fail when the image is missing or Railway's deployment does (#1660).

Railway accepted a deploy of an image GHCR no longer held, the deployment died at
CREATE_CONTAINER, and the pipeline went green because ``/healthz`` answered from the old container.
These run ``scripts/railway-deploy.sh`` against a stub ``curl`` standing in for GHCR and Railway.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY = REPO_ROOT / "scripts" / "railway-deploy.sh"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
IMAGE = "ghcr.io/alexsiri7/reli:abc123"

STUB_CURL = """\
import json, os, sys

args = sys.argv[1:]
url = next(a for a in args if a.startswith("https://"))
calls = os.environ["STUB_CALLS"]
if url.startswith("https://ghcr.io/token"):
    print(json.dumps({"token": "anonymous"}))
elif url.startswith("https://ghcr.io/v2/"):
    manifests = json.loads(os.environ["STUB_MANIFESTS"])
    ref = url.rsplit("/", 1)[1]
    if ref not in manifests:
        sys.exit(22)
    print(json.dumps(manifests[ref]))
else:
    query = json.loads(args[args.index("-d") + 1])["query"]
    with open(calls, "a") as log:
        log.write(query + "\\n")
    if "serviceInstanceUpdate" in query:
        print(json.dumps({"data": {"serviceInstanceUpdate": True}}))
    elif "serviceInstanceDeployV2" in query:
        print(json.dumps({"data": {"serviceInstanceDeployV2": "deployment-1"}}))
    else:
        with open(os.environ["STUB_STATUSES"]) as f:
            statuses = f.read().split()
        with open(os.environ["STUB_STATUSES"], "w") as f:
            f.write(" ".join(statuses[1:] or statuses))
        print(json.dumps({"data": {"deployment": {"status": statuses[0]}}}))
"""

IMAGE_DIGEST = "sha256:image"
ATTESTATION_DIGEST = "sha256:attestation"
INDEX = {
    "mediaType": "application/vnd.oci.image.index.v1+json",
    "manifests": [
        {"digest": IMAGE_DIGEST, "platform": {"architecture": "amd64", "os": "linux"}},
        {
            "digest": ATTESTATION_DIGEST,
            "platform": {"architecture": "unknown", "os": "unknown"},
            "annotations": {"vnd.docker.reference.type": "attestation-manifest"},
        },
    ],
}
IMAGE_MANIFEST = {"mediaType": "application/vnd.oci.image.manifest.v1+json"}
PULLABLE = {"abc123": INDEX, IMAGE_DIGEST: IMAGE_MANIFEST}


def _deploy(tmp_path: Path, manifests: dict, statuses: list[str]) -> tuple[subprocess.CompletedProcess, list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(f"#!{sys.executable}\n{STUB_CURL}")
    curl.chmod(0o755)
    calls = tmp_path / "calls"
    calls.touch()
    (tmp_path / "statuses").write_text(" ".join(statuses))
    result = subprocess.run(
        ["bash", str(DEPLOY), IMAGE],
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "RAILWAY_TOKEN": "token",
            "SERVICE_ID": "service",
            "ENV_ID": "environment",
            "RAILWAY_POLL_SECONDS": "0",
            "RAILWAY_POLL_ATTEMPTS": "3",
            "STUB_MANIFESTS": json.dumps(manifests),
            "STUB_STATUSES": str(tmp_path / "statuses"),
            "STUB_CALLS": str(calls),
        },
        capture_output=True,
        text=True,
    )
    return result, calls.read_text().splitlines()


def test_a_missing_tag_is_refused_before_railway_is_touched(tmp_path):
    result, railway_calls = _deploy(tmp_path, {}, ["SUCCESS"])

    assert result.returncode != 0
    assert f"Image {IMAGE} does not exist in GHCR" in result.stderr
    assert railway_calls == []


def test_a_tag_whose_image_manifest_was_deleted_is_refused(tmp_path):
    """The shape #1660 actually left behind: the tag resolves, the platform image under it does not."""
    result, railway_calls = _deploy(tmp_path, {"abc123": INDEX}, ["SUCCESS"])

    assert result.returncode != 0
    assert f"its image manifest {IMAGE_DIGEST} is gone" in result.stderr
    assert railway_calls == []


def test_a_deployment_railway_reports_successful_passes(tmp_path):
    """The attestation manifest is never pulled, so its absence does not block the deploy."""
    result, railway_calls = _deploy(tmp_path, PULLABLE, ["QUEUED", "DEPLOYING", "SUCCESS"])

    assert result.returncode == 0, result.stderr
    assert [call.split("{")[1].split("(")[0] for call in railway_calls] == [
        "serviceInstanceUpdate",
        "serviceInstanceDeployV2",
        "deployment",
        "deployment",
        "deployment",
    ]


def test_a_deployment_that_ends_failed_fails_the_deploy(tmp_path):
    result, _ = _deploy(tmp_path, PULLABLE, ["DEPLOYING", "FAILED"])

    assert result.returncode != 0
    assert "Railway deployment deployment-1 of" in result.stderr
    assert "ended FAILED" in result.stderr


def test_a_deployment_that_crashes_fails_the_deploy(tmp_path):
    result, _ = _deploy(tmp_path, PULLABLE, ["CRASHED"])

    assert result.returncode != 0
    assert "ended CRASHED" in result.stderr


def test_a_deployment_that_never_settles_fails_the_deploy(tmp_path):
    result, railway_calls = _deploy(tmp_path, PULLABLE, ["DEPLOYING"])

    assert result.returncode != 0
    assert "still not SUCCESS after 3 polls" in result.stderr
    assert sum("deployment(" in call for call in railway_calls) == 3


def _steps(workflow: str) -> list[dict]:
    document = yaml.safe_load((WORKFLOWS / workflow).read_text())
    return [step for job in document["jobs"].values() for step in job.get("steps", [])]


def test_both_pipeline_deploys_go_through_the_checked_script():
    deploys = [step for step in _steps("staging-pipeline.yml") if "Deploy" in step.get("name", "")]

    assert [step["name"] for step in deploys] == [
        "Deploy staging image to Railway",
        "Deploy production image to Railway",
    ]
    assert all(step["run"].startswith("./scripts/railway-deploy.sh ") for step in deploys)


def test_no_workflow_deletes_container_images():
    """A count-based prune deleted image manifests that newer tags still pointed at (#1660)."""
    workflows = sorted(p.name for p in WORKFLOWS.iterdir() if p.suffix in (".yml", ".yaml"))
    deleting = [w for w in workflows for step in _steps(w) if "delete-package-versions" in step.get("uses", "")]

    assert deleting == []
