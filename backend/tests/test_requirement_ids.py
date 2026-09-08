"""Tests for the id/filename and issue-linkage integrity of requirements/*.md (#1399, #1403)."""

import re
from pathlib import Path

import yaml

REQUIREMENTS_ROOT = Path(__file__).resolve().parent.parent.parent / "requirements"

FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
ISSUES_SECTION = re.compile(r"^## Issues$(.*?)(?=^## |\Z)", re.DOTALL | re.MULTILINE)
ISSUE_REFERENCE = re.compile(r"#(\d+)")

SWEEP_REQUIREMENT_ISSUES = {"015": {1137, 1138}, "016": {1139, 1140}, "017": {1141, 1142}}


def _requirement_files() -> list[Path]:
    return sorted(REQUIREMENTS_ROOT.glob("[0-9][0-9][0-9]-*.md"))


def _front_matter(path: Path) -> dict:
    match = FRONT_MATTER.match(path.read_text())
    assert match, f"{path.name} has no YAML front matter"
    return yaml.safe_load(match.group(1))


def test_requirement_files_exist():
    """The requirements directory must hold numbered requirement files."""
    assert _requirement_files(), f"no numbered requirement files under {REQUIREMENTS_ROOT}"


def test_requirement_ids_are_unique():
    """Every requirement must claim an id no other requirement claims."""
    owners: dict[str, list[str]] = {}
    for path in _requirement_files():
        owners.setdefault(str(_front_matter(path)["id"]), []).append(path.name)

    collisions = {rid: names for rid, names in owners.items() if len(names) > 1}
    assert not collisions, f"duplicate requirement ids: {collisions}"


def test_requirement_filename_prefix_matches_id():
    """A requirement's filename prefix must match its front-matter id."""
    for path in _requirement_files():
        assert path.name.split("-")[0] == str(_front_matter(path)["id"]), (
            f"{path.name} declares id {_front_matter(path)['id']!r}"
        )


def _linked_issues(path: Path) -> set[int]:
    """Issue numbers referenced in a file's ## Issues section, empty if it has none."""
    match = ISSUES_SECTION.search(path.read_text())
    if not match:
        return set()
    return {int(number) for number in ISSUE_REFERENCE.findall(match.group(1))}


def test_sweep_requirements_link_their_issues():
    """The sweep requirements must link their own issues and no longer be drafts (#1403)."""
    by_id = {str(_front_matter(path)["id"]): path for path in _requirement_files()}
    missing = SWEEP_REQUIREMENT_ISSUES.keys() - by_id.keys()
    assert not missing, f"sweep requirements no longer present under their ids: {sorted(missing)}"

    for rid, expected in SWEEP_REQUIREMENT_ISSUES.items():
        path = by_id[rid]
        assert _linked_issues(path) == expected, f"{path.name} links the wrong issues"
        assert _front_matter(path)["status"] != "draft", f"{path.name} is still a draft"


def test_linked_issues_are_not_shared_between_requirements():
    """An issue belongs to one requirement, so no two files may link the same number."""
    owners: dict[int, list[str]] = {}
    for path in _requirement_files():
        for issue in _linked_issues(path):
            owners.setdefault(issue, []).append(path.name)

    shared = {issue: names for issue, names in owners.items() if len(names) > 1}
    assert not shared, f"issues linked by more than one requirement: {shared}"
