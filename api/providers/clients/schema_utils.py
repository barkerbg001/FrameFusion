"""JSON-schema adjustments needed by individual providers."""

from __future__ import annotations

import copy
from typing import Any


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve local ``$ref``s against ``$defs`` and drop the definitions block."""
    schema = copy.deepcopy(schema)
    definitions = {**schema.pop("definitions", {}), **schema.pop("$defs", {})}

    def resolve(node: Any, depth: int = 0) -> Any:
        if depth > 32:
            return {}
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith(("#/$defs/", "#/definitions/")):
                target = definitions.get(ref.rsplit("/", 1)[-1], {})
                merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
                return resolve(merged, depth + 1)
            return {key: resolve(value, depth + 1) for key, value in node.items()}
        if isinstance(node, list):
            return [resolve(item, depth + 1) for item in node]
        return node

    return resolve(schema)


def strip_keys(schema: Any, keys: set[str]) -> Any:
    if isinstance(schema, dict):
        return {k: strip_keys(v, keys) for k, v in schema.items() if k not in keys}
    if isinstance(schema, list):
        return [strip_keys(item, keys) for item in schema]
    return schema
