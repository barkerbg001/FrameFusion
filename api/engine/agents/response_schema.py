from typing import Any

from pydantic import BaseModel


def _strip_defaults(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _strip_defaults(value) for key, value in node.items() if key != "default"}
    if isinstance(node, list):
        return [_strip_defaults(item) for item in node]
    return node


def response_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return a provider-neutral JSON schema with property defaults removed."""
    return _strip_defaults(model.model_json_schema())
