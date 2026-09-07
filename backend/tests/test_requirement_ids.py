"""Tests for the id/filename integrity of requirements/*.md (#1399)."""

import re
from pathlib import Path

import yaml

REQUIREMENTS_ROOT = Path(__file__).resolve().parent.parent.parent / "requirements"

FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


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
