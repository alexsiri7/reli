#!/usr/bin/env python3
"""`npm audit` over the whole frontend tree, devDependencies included, failing on every advisory
except the ones recorded in EXCEPTIONS (#1880).

npm has no way to excuse a single advisory, so this runs `npm audit --json` and judges the report
itself. It fails on an advisory with no entry, on an entry whose advisory is no longer reported,
and on an entry whose package now has a non-breaking fix, so an exception cannot outlive the
reason it was granted. Shipped dependencies get no exceptions: CI audits them separately with a
bare `npm audit --omit=dev`.

Run from `frontend/`.
"""

import json
import subprocess
import sys

# Each entry: why the advisory cannot be fixed yet, and when the entry goes.
EXCEPTIONS = {
    "GHSA-fc5q-39xc-vjpf": (
        "picomatch ReDoS through repeated extglobs, with no patched release (latest 4.0.7 on "
        "2026-11-18). It is reached only through the devDependencies vite and typescript-eslint, "
        "which match the repository's own globs at build and lint time; nothing shipped contains "
        "it. Remove this entry once picomatch ships a fix (#1880)."
    ),
}


def advisories(report: dict) -> dict[str, list[str]]:
    """GHSA id -> the packages it is reported against, for every advisory the report names. A `via`
    that is a string names a package that is only vulnerable through another one, whose own entry
    carries the advisory."""
    found: dict[str, list[str]] = {}
    for package, vulnerability in report["vulnerabilities"].items():
        for via in vulnerability["via"]:
            if isinstance(via, dict):
                found.setdefault(via["url"].rsplit("/", 1)[-1], []).append(package)
    return found


def problems(report: dict) -> list[str]:
    if "vulnerabilities" not in report:
        return [f"npm audit did not produce a report: {json.dumps(report)[:500]}"]
    found = advisories(report)
    vulnerabilities = report["vulnerabilities"]
    return [
        *(
            f"{ghsa} in {', '.join(packages)} has no recorded exception"
            for ghsa, packages in sorted(found.items())
            if ghsa not in EXCEPTIONS
        ),
        *(f"{ghsa} is no longer reported: remove its exception" for ghsa in sorted(EXCEPTIONS.keys() - found.keys())),
        *(
            f"{ghsa} in {package} now has a non-breaking fix: run `npm audit fix` and remove its exception"
            for ghsa in sorted(EXCEPTIONS.keys() & found.keys())
            for package in found[ghsa]
            if vulnerabilities[package]["fixAvailable"] is True
        ),
    ]


def main() -> int:
    result = subprocess.run(["npm", "audit", "--json"], capture_output=True, text=True)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(result.stdout, result.stderr, sep="\n", file=sys.stderr)
        print("npm audit did not produce a JSON report", file=sys.stderr)
        return 1
    failures = problems(report)
    for failure in failures:
        print(failure, file=sys.stderr)
    if failures:
        return 1
    for ghsa, reason in EXCEPTIONS.items():
        print(f"excused {ghsa}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
