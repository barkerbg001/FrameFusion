from engine.agents.response_schema import response_schema
from engine.orchestrator.schemas import ProductionBrief, ScriptArtifact


def test_response_schema_strips_defaults() -> None:
    schema = {
        "brief": response_schema(ProductionBrief),
        "script": response_schema(ScriptArtifact),
    }

    def collect_defaults(node: object) -> list[object]:
        found: list[object] = []
        if isinstance(node, dict):
            if "default" in node:
                found.append(node["default"])
            for value in node.values():
                found.extend(collect_defaults(value))
        elif isinstance(node, list):
            for item in node:
                found.extend(collect_defaults(item))
        return found

    assert collect_defaults(schema) == []
