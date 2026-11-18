"""The frontend audit excuses only the advisories it records, and only while they stay unfixable.

#1880: `scripts/npm_audit.py` runs `npm audit` over the whole tree and judges the report. It is
run here against a stub `npm` that logs its arguments and prints a canned report.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT = REPO_ROOT / "scripts" / "npm_audit.py"
EXCUSED = "GHSA-fc5q-39xc-vjpf"


def _advisory(ghsa: str) -> dict:
    return {"source": 1, "name": "pkg", "url": f"https://github.com/advisories/{ghsa}", "severity": "high"}


def _report(*entries: tuple[str, list, object]) -> dict:
    return {
        "vulnerabilities": {
            package: {"name": package, "severity": "high", "via": via, "fixAvailable": fix}
            for package, via, fix in entries
        }
    }


UNFIXABLE = ("picomatch", [_advisory(EXCUSED)], {"name": "vite", "version": "6.2.7", "isSemVerMajor": True})
THROUGH_IT = ("vite", ["picomatch"], {"name": "vite", "version": "6.2.7", "isSemVerMajor": True})


def _run(tmp_path: Path, stdout: str) -> subprocess.CompletedProcess:
    stub = tmp_path / "npm"
    (tmp_path / "report").write_text(stdout)
    stub.write_text(f'#!/usr/bin/env bash\necho "$*" >> {tmp_path}/args\ncat {tmp_path}/report\nexit 1\n')
    stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run([sys.executable, str(AUDIT)], env=env, capture_output=True, text=True)


def test_it_audits_the_whole_tree_and_passes_on_the_recorded_advisory(tmp_path):
    result = _run(tmp_path, json.dumps(_report(UNFIXABLE, THROUGH_IT)))

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "args").read_text() == "audit --json\n"
    assert f"excused {EXCUSED}" in result.stdout


@pytest.mark.parametrize(
    ("report", "complaint"),
    [
        (_report(UNFIXABLE, ("esbuild", [_advisory("GHSA-aaaa-bbbb-cccc")], True)), "GHSA-aaaa-bbbb-cccc in esbuild"),
        (_report(("esbuild", [_advisory("GHSA-aaaa-bbbb-cccc")], False)), f"{EXCUSED} is no longer reported"),
        (_report(("picomatch", [_advisory(EXCUSED)], True)), "now has a non-breaking fix"),
        ({"error": {"code": "ENOLOCK"}}, "did not produce a report"),
    ],
    ids=["another-advisory", "advisory-gone", "fix-released", "npm-error"],
)
def test_it_fails_on_anything_else(tmp_path, report, complaint):
    result = _run(tmp_path, json.dumps(report))

    assert result.returncode == 1
    assert complaint in result.stderr


def test_it_fails_when_npm_prints_no_report(tmp_path):
    assert _run(tmp_path, "npm ERR! network").returncode == 1


def test_every_exception_is_named_and_gives_its_reason():
    """The owner's terms (#1880): a named advisory, a recorded reason, and when the entry goes."""
    spec = importlib.util.spec_from_file_location("npm_audit", AUDIT)
    assert spec and spec.loader
    npm_audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(npm_audit)

    for ghsa, reason in npm_audit.EXCEPTIONS.items():
        assert re.fullmatch(r"GHSA(-[23456789cfghjmpqrvwx]{4}){3}", ghsa), ghsa
        assert re.search(r"Remove this entry once .+ \(#\d+\)\.$", reason), ghsa
