"""The Docker build context keeps out every legacy data store ``.gitignore`` keeps out (#1706).

``COPY backend/ ./backend/`` takes whatever the working tree holds, so a legacy store or export
``.gitignore`` hides from the repository reaches the image unless ``.dockerignore`` hides it too.
The two lists are kept in step here: a pattern added to ``.gitignore``'s legacy-data blocks fails
this test until ``.dockerignore`` carries it as well.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_BLOCK_HEADERS = ("# Legacy data", "# Graph exports and database dumps")


def _legacy_gitignore_patterns() -> list[str]:
    patterns = []
    for block in (REPO_ROOT / ".gitignore").read_text().split("\n\n"):
        lines = block.strip().splitlines()
        if lines and lines[0].startswith(LEGACY_BLOCK_HEADERS):
            patterns += [line for line in lines if line and not line.startswith("#")]
    return patterns


def test_the_legacy_blocks_are_found():
    assert "*.db" in _legacy_gitignore_patterns()
    assert "*.sql.gz" in _legacy_gitignore_patterns()


def _at_any_depth(gitignore_pattern: str) -> str:
    """The .dockerignore form of a pattern: a slash-free one there matches the context root only.

    A rooted path such as ``backend/chroma_db/`` is covered by its last segment at any depth.
    """
    directory = "/" if gitignore_pattern.endswith("/") else ""
    return "**/" + gitignore_pattern.rstrip("/").rsplit("/", 1)[-1] + directory


def test_dockerignore_excludes_every_legacy_pattern_at_any_depth():
    dockerignore = set((REPO_ROOT / ".dockerignore").read_text().splitlines())
    missing = [p for p in _legacy_gitignore_patterns() if _at_any_depth(p) not in dockerignore]
    assert not missing, f".dockerignore does not exclude {missing} at any depth"
