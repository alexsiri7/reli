#!/usr/bin/env python3
"""Generate TypeScript interfaces and Zod schemas from Pydantic models via OpenAPI.

Usage:
    python scripts/generate_types.py

This script:
1. Imports the FastAPI app and extracts its OpenAPI schema
2. Converts component schemas to TypeScript interfaces
3. Converts component schemas to Zod validation schemas
4. Writes both to frontend/src/generated/api-types.ts
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from typing import Any

# Add project root so we can import the backend
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_FILE = PROJECT_ROOT / "frontend" / "src" / "generated" / "api-types.ts"

# Models that the frontend actually uses (response models only — not Create/Update).
# Maps OpenAPI schema name → exported TypeScript name.
# Models not in this list are skipped to avoid bloating the generated file.
EXPORTED_MODELS: dict[str, str] = {
    # models.py
    "ThingType": "ThingType",
    "Thing": "Thing",
    "GraphNode": "GraphNode",
    "GraphEdge": "GraphEdge",
    "GraphResponse": "GraphResponse",
    "Relationship": "Relationship",
    "CallUsage": "CallUsage",
    "ChatMessage": "ChatMessage",
    "ChatResponse": "ChatResponse",
    "UsageInfo": "UsageInfo",
    "ModelUsage": "ModelUsage",
    "SessionUsage": "SessionUsage",
    "SweepFinding": "SweepFinding",
    "BriefingItem": "BriefingItem",
    "BriefingResponse": "BriefingResponse",
    "StaleItem": "StaleItem",
    "OverdueCheckin": "OverdueCheckin",
    "StalenessCategory": "StalenessCategory",
    "StalenessReport": "StalenessReport",
    "MorningBriefingItem": "MorningBriefingItem",
    "MorningBriefingFinding": "MorningBriefingFinding",
    "MorningBriefingContent": "MorningBriefingContent",
    "MorningBriefing": "MorningBriefing",
    "BriefingPreferences": "BriefingPreferences",
    "Nudge": "Nudge",
    "WeeklyBriefingItem": "WeeklyBriefingItem",
    "WeeklyBriefingConnection": "WeeklyBriefingConnection",
    "WeeklyBriefingContent": "WeeklyBriefingContent",
    "WeeklyBriefing": "WeeklyBriefing",
    "ProactiveSurface": "ProactiveSurface",
    "FocusRecommendation": "FocusRecommendation",
    "FocusResponse": "FocusResponse",
    "ConflictAlertResponse": "ConflictAlert",
    "MergeSuggestionThing": "MergeSuggestionThing",
    "MergeSuggestion": "MergeSuggestion",
    "MergeResult": "MergeResult",
    "ConnectionSuggestionThing": "ConnectionSuggestionThing",
    "ConnectionSuggestion": "ConnectionSuggestion",
    # routers/settings.py
    "ModelSettings": "ModelSettings",
    "UserSettings": "UserSettings",
    "RequestyModel": "RequestyModel",
    # routers/things.py
    "UserProfileRelationship": "UserProfileRelationship",
    "UserProfileDetail": "UserProfile",
}

# Pydantic models to import directly when they're missing from OpenAPI
# (e.g. router not yet mounted). Maps class import path → OpenAPI-style name.
_FALLBACK_MODELS: dict[str, str] = {
    "backend.models.Nudge": "Nudge",
}


def get_openapi_schema() -> dict[str, Any]:
    """Import the FastAPI app and extract its OpenAPI schema.

    Also injects fallback models that aren't in the OpenAPI schema yet
    (e.g. routers not mounted) by calling model_json_schema() directly.
    """
    import importlib
    import os

    os.environ.setdefault("DATA_DIR", "/tmp")
    os.environ.setdefault("SECRET_KEY", "generate-types-dummy-key")
    os.environ.setdefault("GOOGLE_CLIENT_ID", "dummy")
    os.environ.setdefault("GOOGLE_CLIENT_SECRET", "dummy")
    os.environ.setdefault("DATABASE_URL", "sqlite:///tmp/dummy.db")

    from backend.main import app

    schema = app.openapi()

    # Inject fallback models not yet in OpenAPI
    component_schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    for import_path, schema_name in _FALLBACK_MODELS.items():
        if schema_name not in component_schemas:
            module_path, class_name = import_path.rsplit(".", 1)
            mod = importlib.import_module(module_path)
            model_cls = getattr(mod, class_name)
            component_schemas[schema_name] = model_cls.model_json_schema()

    return schema


# ---------------------------------------------------------------------------
# JSON Schema → TypeScript conversion
# ---------------------------------------------------------------------------


def resolve_ref(ref: str) -> str:
    """Extract the schema name from a $ref string like '#/components/schemas/Thing'."""
    return ref.rsplit("/", 1)[-1]


def json_schema_to_ts(prop: dict[str, Any], schemas: dict[str, Any], required: bool = True) -> str:
    """Convert a JSON Schema property definition to a TypeScript type string."""
    # Handle $ref
    if "$ref" in prop:
        ref_name = resolve_ref(prop["$ref"])
        ts_name = EXPORTED_MODELS.get(ref_name, ref_name)
        return ts_name

    # Handle anyOf (used by Pydantic for Optional/Union types)
    if "anyOf" in prop:
        types = prop["anyOf"]
        non_null = [t for t in types if t.get("type") != "null"]
        has_null = any(t.get("type") == "null" for t in types)

        if len(non_null) == 1:
            base = json_schema_to_ts(non_null[0], schemas)
            return f"{base} | null" if has_null else base
        else:
            parts = [json_schema_to_ts(t, schemas) for t in non_null]
            union = " | ".join(parts)
            return f"{union} | null" if has_null else union

    # Handle allOf (single-element allOf is common in Pydantic v2)
    if "allOf" in prop:
        if len(prop["allOf"]) == 1:
            return json_schema_to_ts(prop["allOf"][0], schemas)
        # Multi-element allOf: intersection type
        parts = [json_schema_to_ts(t, schemas) for t in prop["allOf"]]
        return " & ".join(parts)

    schema_type = prop.get("type")

    if schema_type == "string":
        return "string"
    if schema_type == "integer" or schema_type == "number":
        return "number"
    if schema_type == "boolean":
        return "boolean"
    if schema_type == "null":
        return "null"

    if schema_type == "array":
        items = prop.get("items", {})
        item_type = json_schema_to_ts(items, schemas)
        return f"{item_type}[]"

    if schema_type == "object":
        # Check for additionalProperties (Record type)
        additional = prop.get("additionalProperties")
        if additional:
            if isinstance(additional, dict):
                val_type = json_schema_to_ts(additional, schemas)
            else:
                val_type = "unknown"
            return f"Record<string, {val_type}>"
        # Plain object without properties
        if not prop.get("properties"):
            return "Record<string, unknown>"

    return "unknown"


def schema_to_interface(name: str, schema: dict[str, Any], all_schemas: dict[str, Any]) -> str:
    """Convert a JSON Schema object definition to a TypeScript interface.

    All fields in properties are treated as required because Pydantic always
    includes them in serialized output (even fields with defaults or
    default_factory). Nullability is expressed via `| null` in the type, not
    via optionality (`?`).
    """
    ts_name = EXPORTED_MODELS.get(name, name)
    props = schema.get("properties", {})

    lines = [f"export interface {ts_name} {{"]
    for prop_name, prop_def in props.items():
        ts_type = json_schema_to_ts(prop_def, all_schemas)
        lines.append(f"  {prop_name}: {ts_type}")
    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON Schema → Zod conversion
# ---------------------------------------------------------------------------


def json_schema_to_zod(prop: dict[str, Any], schemas: dict[str, Any], required: bool = True) -> str:
    """Convert a JSON Schema property definition to a Zod schema expression."""
    # Handle $ref
    if "$ref" in prop:
        ref_name = resolve_ref(prop["$ref"])
        ts_name = EXPORTED_MODELS.get(ref_name, ref_name)
        return f"{ts_name}Schema"

    # Handle anyOf (Optional/Union)
    if "anyOf" in prop:
        types = prop["anyOf"]
        non_null = [t for t in types if t.get("type") != "null"]
        has_null = any(t.get("type") == "null" for t in types)

        if len(non_null) == 1:
            base = json_schema_to_zod(non_null[0], schemas)
            return f"{base}.nullable()" if has_null else base
        else:
            parts = [json_schema_to_zod(t, schemas) for t in non_null]
            union = f"z.union([{', '.join(parts)}])"
            return f"{union}.nullable()" if has_null else union

    # Handle allOf
    if "allOf" in prop:
        if len(prop["allOf"]) == 1:
            return json_schema_to_zod(prop["allOf"][0], schemas)
        parts = [json_schema_to_zod(t, schemas) for t in prop["allOf"]]
        base = parts[0]
        for p in parts[1:]:
            base = f"{base}.and({p})"
        return base

    schema_type = prop.get("type")

    if schema_type == "string":
        return "z.string()"
    if schema_type == "integer" or schema_type == "number":
        return "z.number()"
    if schema_type == "boolean":
        return "z.boolean()"
    if schema_type == "null":
        return "z.null()"

    if schema_type == "array":
        items = prop.get("items", {})
        item_zod = json_schema_to_zod(items, schemas)
        return f"z.array({item_zod})"

    if schema_type == "object":
        additional = prop.get("additionalProperties")
        if additional:
            if isinstance(additional, dict):
                val_zod = json_schema_to_zod(additional, schemas)
            else:
                val_zod = "z.unknown()"
            return f"z.record(z.string(), {val_zod})"
        if not prop.get("properties"):
            return "z.record(z.string(), z.unknown())"

    return "z.unknown()"


def _is_nullable_type(prop_def: dict[str, Any]) -> bool:
    """Check if a JSON Schema property allows null."""
    if "anyOf" in prop_def:
        return any(t.get("type") == "null" for t in prop_def["anyOf"])
    return prop_def.get("type") == "null"


def schema_to_zod(name: str, schema: dict[str, Any], all_schemas: dict[str, Any]) -> str:
    """Convert a JSON Schema object definition to a Zod schema declaration.

    For fields not in `required`: if an explicit default exists, use .default();
    if the field is nullable (Pydantic `= None`), use .default(null);
    otherwise use .optional().
    """
    ts_name = EXPORTED_MODELS.get(name, name)
    props = schema.get("properties", {})
    required_set = set(schema.get("required", []))

    lines = [f"export const {ts_name}Schema = z.object({{"]
    for prop_name, prop_def in props.items():
        zod_type = json_schema_to_zod(prop_def, all_schemas)
        optional = prop_name not in required_set
        if optional:
            if "default" in prop_def:
                default_val = prop_def["default"]
                if default_val is None:
                    zod_type = f"{zod_type}.nullable().default(null)"
                elif isinstance(default_val, bool):
                    zod_type = f"{zod_type}.default({'true' if default_val else 'false'})"
                elif isinstance(default_val, (int, float)):
                    zod_type = f"{zod_type}.default({default_val})"
                elif isinstance(default_val, str):
                    zod_type = f"{zod_type}.default({json.dumps(default_val)})"
                elif isinstance(default_val, list):
                    zod_type = f"{zod_type}.default([])"
                elif isinstance(default_val, dict):
                    zod_type = f"{zod_type}.default({{}})"
                else:
                    zod_type = f"{zod_type}.optional()"
            elif _is_nullable_type(prop_def):
                # Pydantic `field: T | None = None` — no explicit default in schema
                # but always serialized as null. Use .default(null).
                zod_type = f"{zod_type}.default(null)"
            elif prop_def.get("type") == "array":
                # Pydantic `Field(default_factory=list)` — always serialized as []
                zod_type = f"{zod_type}.default([])"
            elif prop_def.get("type") == "object" and prop_def.get("additionalProperties"):
                # Pydantic `Field(default_factory=dict)` — always serialized as {{}}
                zod_type = f"{zod_type}.default({{}})"
            else:
                zod_type = f"{zod_type}.optional()"
        lines.append(f"  {prop_name}: {zod_type},")
    lines.append("})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dependency ordering
# ---------------------------------------------------------------------------


def get_schema_deps(schema: dict[str, Any]) -> set[str]:
    """Extract all $ref dependencies from a schema."""
    deps: set[str] = set()
    _walk_for_refs(schema, deps)
    return deps


def _walk_for_refs(node: Any, deps: set[str]) -> None:
    if isinstance(node, dict):
        if "$ref" in node:
            deps.add(resolve_ref(node["$ref"]))
        for v in node.values():
            _walk_for_refs(v, deps)
    elif isinstance(node, list):
        for item in node:
            _walk_for_refs(item, deps)


def topological_sort(schemas: dict[str, Any], names: list[str]) -> list[str]:
    """Sort schema names so that dependencies come before dependents."""
    name_set = set(names)
    visited: set[str] = set()
    result: list[str] = []

    def visit(name: str) -> None:
        if name in visited or name not in name_set:
            return
        visited.add(name)
        schema = schemas.get(name, {})
        for dep in get_schema_deps(schema):
            if dep in name_set:
                visit(dep)
        result.append(name)

    for name in names:
        visit(name)
    return result


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------


def generate() -> str:
    """Generate the full TypeScript file content."""
    openapi = get_openapi_schema()
    all_schemas = openapi.get("components", {}).get("schemas", {})

    # Filter to only exported models
    exported_names = [name for name in EXPORTED_MODELS if name in all_schemas]

    # Sort by dependency order
    sorted_names = topological_sort(all_schemas, exported_names)

    # Generate interfaces
    interfaces: list[str] = []
    zod_schemas: list[str] = []

    for name in sorted_names:
        schema = all_schemas[name]
        interfaces.append(schema_to_interface(name, schema, all_schemas))
        zod_schemas.append(schema_to_zod(name, schema, all_schemas))

    # Build output
    header = textwrap.dedent("""\
        /**
         * AUTO-GENERATED — DO NOT EDIT
         *
         * Generated from Pydantic models via OpenAPI schema.
         * Run `npm run generate:types` to regenerate.
         *
         * Source: backend/models.py, backend/routers/*.py
         */

        import { z } from 'zod'
    """)

    ts_section = "\n// ═══════════════════════════════════════════════════════════════════════\n"
    ts_section += "// TypeScript Interfaces\n"
    ts_section += "// ═══════════════════════════════════════════════════════════════════════\n\n"
    ts_section += "\n\n".join(interfaces)

    zod_section = "\n\n// ═══════════════════════════════════════════════════════════════════════\n"
    zod_section += "// Zod Validation Schemas\n"
    zod_section += "// ═══════════════════════════════════════════════════════════════════════\n\n"
    zod_section += "\n\n".join(zod_schemas)

    return header + ts_section + "\n" + zod_section + "\n"


def main() -> None:
    check_mode = "--check" in sys.argv

    content = generate()

    if check_mode:
        # Verify generated file is up to date
        if not OUTPUT_FILE.exists():
            print(f"FAIL: {OUTPUT_FILE.relative_to(PROJECT_ROOT)} does not exist")
            print("Run `npm run generate:types` to generate it.")
            sys.exit(1)
        existing = OUTPUT_FILE.read_text()
        if existing != content:
            print(f"FAIL: {OUTPUT_FILE.relative_to(PROJECT_ROOT)} is out of date")
            print("Run `npm run generate:types` to regenerate.")
            sys.exit(1)
        print(f"OK: {OUTPUT_FILE.relative_to(PROJECT_ROOT)} is up to date")
        return

    # Ensure output directory exists
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(content)

    print(f"Generated {OUTPUT_FILE.relative_to(PROJECT_ROOT)}")
    print(f"  {len(EXPORTED_MODELS)} models exported")


if __name__ == "__main__":
    main()
