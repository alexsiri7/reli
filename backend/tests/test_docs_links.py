"""Every relative link and ``#anchor`` in ``docs/*.md``, ``README.md`` and ``CLAUDE.md`` resolves (#1417).

Only inline markdown links (``[text](target)``) are checked, because that is the only link syntax the
checked files use; reference-style links and raw HTML anchors would pass unnoticed. ``https://``
targets are not fetched — the check is against the tree, never the network.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

INLINE_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*```")
EXTERNAL_SCHEMES = ("http://", "https://", "mailto:")


def _checked_files() -> list[Path]:
    return sorted((REPO_ROOT / "docs").glob("*.md")) + [REPO_ROOT / "README.md", REPO_ROOT / "CLAUDE.md"]


def _slug(heading: str) -> str:
    """GitHub's heading-to-anchor rule: lowercase, drop punctuation, spaces to hyphens."""
    text = heading.replace("`", "").lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def _headings(markdown: Path) -> list[str]:
    """Heading text outside fenced code blocks, where GitHub renders ``# comment`` as code, not a heading."""
    headings: list[str] = []
    in_fence = False
    for line in markdown.read_text().splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and (match := HEADING.match(line)):
            headings.append(match.group(1))
    return headings


def _anchors(markdown: Path) -> set[str]:
    """Every anchor the file's headings produce; a repeated slug gets ``-1``, ``-2`` and so on."""
    seen: dict[str, int] = {}
    anchors: set[str] = set()
    for heading in _headings(markdown):
        slug = _slug(heading)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


def _dead_links() -> list[str]:
    dead: list[str] = []
    for source in _checked_files():
        for target in INLINE_LINK.findall(source.read_text()):
            if target.startswith(EXTERNAL_SCHEMES):
                continue
            path_part, _, fragment = target.partition("#")
            resolved = (source.parent / path_part).resolve() if path_part else source
            label = f"{source.relative_to(REPO_ROOT)} -> {target}"
            if not resolved.exists():
                dead.append(f"{label} (missing file)")
            elif fragment and resolved.suffix == ".md" and fragment not in _anchors(resolved):
                dead.append(f"{label} (missing anchor)")
    return dead


def test_checked_files_exist():
    assert len(_checked_files()) > 2, f"no docs found under {REPO_ROOT / 'docs'}"


def test_headings_inside_fenced_code_blocks_are_not_anchors(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text(
        "# Real Heading\n\n```bash\n# Fake Heading\necho hi\n```\n\n"
        "- step\n\n   ```\n# Fake Under Indented Fence\n   ```\n\n## After\n"
    )
    assert _anchors(md) == {"real-heading", "after"}


def test_relative_links_resolve():
    dead = _dead_links()
    assert not dead, "dead links:\n" + "\n".join(dead)
