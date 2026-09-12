"""Structural invariants: no model dependency, and one write path.

These read the source rather than the runtime because that is what they assert — that the code
cannot reach a model, and that nothing but the service layer builds a Thing.
"""

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent

# The vision's first rule: no LLM call originates inside the Reli service.
FORBIDDEN_IMPORTS = ("openai", "litellm", "google.adk", "anthropic", "chromadb", "pgvector")

WRITERS = {"service.py", "db_models.py"}


def _backend_sources() -> list[Path]:
    return sorted(path for path in BACKEND.rglob("*.py") if "tests" not in path.parts)


def test_there_are_backend_sources_to_scan():
    """Guard the two scans below against silently passing on an empty file list."""
    assert len(_backend_sources()) >= 5


@pytest.mark.parametrize("module", FORBIDDEN_IMPORTS)
def test_no_backend_module_imports_a_model_client(module):
    pattern = re.compile(rf"^\s*(?:import|from)\s+{re.escape(module)}\b", re.MULTILINE)
    offenders = [
        path.relative_to(BACKEND).as_posix() for path in _backend_sources() if pattern.search(path.read_text())
    ]
    assert offenders == [], f"{module} is imported by {offenders}"


@pytest.mark.parametrize("record", ["ThingRecord", "RelationshipRecord"])
def test_records_are_constructed_only_by_the_service_layer(record):
    """Every mutation must go through backend/service.py, which journals it."""
    pattern = re.compile(rf"\b{record}\(")
    offenders = [
        path.relative_to(BACKEND).as_posix()
        for path in _backend_sources()
        if path.name not in WRITERS and pattern.search(path.read_text())
    ]
    assert offenders == [], f"{record} is constructed outside the service layer by {offenders}"


GOOGLE_MODULES = ("google_login.py",)

# #938 was a Gmail token left on disk after a migration. What keeps it from recurring is that the
# code holding a Google credential has no way to write one down.
CREDENTIAL_SINKS = ("open(", ".write_text(", ".write_bytes(", "json.dump(", "sqlmodel", "db_engine", "db_models")


@pytest.mark.parametrize("module", GOOGLE_MODULES)
def test_the_google_modules_never_persist_a_credential(module):
    source = (BACKEND / module).read_text()

    assert [sink for sink in CREDENTIAL_SINKS if sink in source] == []
