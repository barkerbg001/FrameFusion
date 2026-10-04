import json
from types import SimpleNamespace
from typing import Any

import pytest

from engine.agents.response_schema import (
    StructuredOutputError,
    generate_validated,
    response_schema,
)
from engine.orchestrator.schemas import ProductionBrief, ScriptArtifact
from engine.schemas.idea import IdeaDraft
from engine.schemas.research import ResearchFindings


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


def test_model_facing_schemas_leave_server_fields_out() -> None:
    research = response_schema(ResearchFindings)
    assert research["required"] == ["summary"]
    assert not {"task", "researched_at", "tools_used", "research_data"} & set(
        research["properties"]
    )
    ideas = response_schema(IdeaDraft)
    assert ideas["required"] == ["ideas"]
    assert not {"topic", "generated_at", "tools_used"} & set(ideas["properties"])


class ScriptedClient:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.prompts: list[str] = []
        self.models = SimpleNamespace(generate_content=self.generate_content)

    def generate_content(self, *, model: Any, contents: str, config: Any) -> SimpleNamespace:
        self.prompts.append(contents)
        return SimpleNamespace(text=self.replies.pop(0))


def test_generate_validated_retries_once_with_the_problems() -> None:
    truncated = '{"summary": "Nami is the navigator", "verified_facts": ["a"]'
    client = ScriptedClient([truncated, json.dumps({"summary": "Nami is the navigator"})])

    findings = generate_validated(client, "Summarise.", ResearchFindings, temperature=0)

    assert findings.summary == "Nami is the navigator"
    assert len(client.prompts) == 2
    assert "did not match the required JSON schema" in client.prompts[1]


def test_generate_validated_reports_field_problems_without_echoing_input() -> None:
    reply = json.dumps({"verified_facts": ["x" * 500]})
    client = ScriptedClient([reply, reply])

    with pytest.raises(StructuredOutputError) as caught:
        generate_validated(client, "Summarise.", ResearchFindings, temperature=0)

    assert caught.value.problems == ["summary: Field required"]
    assert "x" * 50 not in str(caught.value)
