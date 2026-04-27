"""Safety guard for destructive DDL operations in Alembic migrations.

Scans pending migration scripts for destructive operations (DROP TABLE,
DROP COLUMN, etc.) and blocks execution unless explicitly allowed via
the ALLOW_DESTRUCTIVE_DDL environment variable.
"""

import ast
import os
import re
from pathlib import Path

from alembic.script import ScriptDirectory

# Alembic op.* calls considered destructive
DESTRUCTIVE_OPS = frozenset(
    {
        "drop_table",
        "drop_column",
        "drop_index",
        "drop_constraint",
        "drop_all",
    }
)

# Raw SQL patterns considered destructive (case-insensitive)
_DESTRUCTIVE_SQL_PATTERNS = [
    re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE),
    re.compile(r"\bALTER\s+TABLE\s+\S+\s+DROP\b", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE),
]


class DestructiveDDLFound(RuntimeError):
    """Raised when a migration contains destructive DDL without explicit opt-in."""


def _find_destructive_ops_in_source(source: str) -> list[str]:
    """Parse Python source and return destructive op.* calls found in upgrade()."""
    findings: list[str] = []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return findings

    for node in ast.walk(tree):
        # Look for function defs named "upgrade"
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            for child in ast.walk(node):
                # op.drop_table(...), op.drop_column(...), etc.
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr in DESTRUCTIVE_OPS
                ):
                    args_repr = ""
                    if child.args:
                        first = child.args[0]
                        if isinstance(first, ast.Constant) and isinstance(first.value, str):
                            args_repr = f"('{first.value}'...)"
                    findings.append(f"op.{child.func.attr}{args_repr}")

                # op.execute("DROP TABLE ...") or raw SQL strings
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "execute"
                    and child.args
                ):
                    first = child.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        for pattern in _DESTRUCTIVE_SQL_PATTERNS:
                            if pattern.search(first.value):
                                findings.append(f"op.execute() with: {first.value[:80]}")
                                break

    return findings


def check_pending_migrations(
    script_dir: ScriptDirectory,
    current_heads: set[str],
) -> None:
    """Check pending migrations for destructive DDL.

    Args:
        script_dir: Alembic ScriptDirectory instance.
        current_heads: Set of current revision IDs in the database.

    Raises:
        DestructiveDDLFound: If destructive DDL is found and
            ALLOW_DESTRUCTIVE_DDL is not set.
    """
    if os.environ.get("ALLOW_DESTRUCTIVE_DDL", "").lower() in ("1", "true", "yes"):
        return

    # Walk pending revisions
    all_findings: dict[str, list[str]] = {}

    for rev_script in script_dir.walk_revisions():
        rev_id = rev_script.revision
        # Skip if already applied
        if rev_id in current_heads:
            continue

        source_path = Path(rev_script.path) if rev_script.path else None
        if source_path is None or not source_path.exists():
            continue

        source = source_path.read_text()
        findings = _find_destructive_ops_in_source(source)

        if findings:
            label = f"{rev_id} ({rev_script.doc or 'no description'})"
            all_findings[label] = findings

    if not all_findings:
        return

    lines = [
        "Destructive DDL detected in pending migrations!",
        "",
        "The following migrations contain operations that could destroy data:",
        "",
    ]
    for label, ops in all_findings.items():
        lines.append(f"  {label}:")
        for op in ops:
            lines.append(f"    - {op}")
    lines.extend(
        [
            "",
            "To apply these migrations, set the environment variable:",
            "  ALLOW_DESTRUCTIVE_DDL=true alembic upgrade head",
            "",
            "Or from Python:",
            '  os.environ["ALLOW_DESTRUCTIVE_DDL"] = "true"',
        ]
    )

    raise DestructiveDDLFound("\n".join(lines))
