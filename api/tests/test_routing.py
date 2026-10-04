from typing import Any

import pytest

from engine.llm import (
    CompletionResult,
    LLMConfigurationError,
    ToolCall,
    get_llm_client,
    types,
    use_llm_resolver,
)
from engine.runtime import get_tool_results, record_tool_result, run_context
from providers import services
from providers.models import AgentModelOverride

from .conftest import FakeRegistry, configure_ai

pytestmark = pytest.mark.django_db


def test_routes_use_their_configured_provider(
    fake_providers: FakeRegistry,
) -> None:
    configure_ai("openrouter", "openai/gpt-4o-mini")
    services.save_api_key("anthropic", "sk-ant-" + "k" * 30)
    AgentModelOverride.objects.create(
        persona="production", provider="anthropic", model="claude-haiku-4-5"
    )
    resolve = services.make_resolver()

    planner = resolve("orchestrator")
    assert planner.provider.name == "openrouter"
    assert planner.model == "openai/gpt-4o-mini"
    assert planner.route == "planner"

    production = resolve("visual")
    assert production.provider.name == "anthropic"
    assert production.model == "claude-haiku-4-5"
    assert production.route == "production"
    assert fake_providers.used_keys["anthropic"] == "sk-ant-" + "k" * 30


def test_unknown_agent_is_rejected(fake_providers: FakeRegistry) -> None:
    configure_ai()
    with pytest.raises(ValueError):
        services.make_resolver()("framey")


def test_missing_key_fails_without_falling_back(fake_providers: FakeRegistry) -> None:
    configure_ai("openrouter", "openai/gpt-4o-mini")
    AgentModelOverride.objects.create(
        persona="production", provider="anthropic", model="claude-haiku-4-5"
    )
    resolve = services.make_resolver()
    with pytest.raises(LLMConfigurationError) as raised:
        resolve("visual")
    assert "visual specialist route" in raised.value.message
    assert "Anthropic Claude" in raised.value.message
    assert "anthropic" not in fake_providers.used_keys
    assert "openrouter" not in fake_providers.fakes


def test_unconfigured_app_gets_settings_guidance(db: Any) -> None:
    resolve = services.make_resolver()
    with pytest.raises(LLMConfigurationError) as raised:
        resolve("orchestrator")
    assert "Settings" in raised.value.message


def test_llm_client_runs_tool_loop(fake_providers: FakeRegistry) -> None:
    configure_ai()
    fake = fake_providers.get("openrouter")
    fake.responses = [
        CompletionResult(
            text="",
            tool_calls=[ToolCall(id="c1", name="lookup_weather", arguments={"city": "Paris"})],
        ),
        CompletionResult(text="It is sunny in Paris.", input_tokens=12, output_tokens=6),
    ]
    calls: list[str] = []

    def lookup_weather(city: str) -> str:
        """Look up the weather.

        Args:
            city: City name.
        """
        calls.append(city)
        record_tool_result("lookup_weather", {"city": city}, {"sky": "sunny"})
        return '{"sky": "sunny"}'

    events: list[tuple[str, dict[str, Any]]] = []
    with (
        use_llm_resolver(services.make_resolver()),
        run_context(lambda event, data: events.append((event, data))),
    ):
        client = get_llm_client("orchestrator")
        response = client.models.generate_content(
            model=client.model_name,
            contents="What's the weather in Paris?",
            config=types.GenerateContentConfig(
                system_instruction="Be brief.", tools=[lookup_weather], temperature=0.3
            ),
        )
        assert get_tool_results()[0]["tool"] == "lookup_weather"

    assert response.text == "It is sunny in Paris."
    assert calls == ["Paris"]
    first, second = fake.requests
    assert first.system == "Be brief."
    assert first.tools[0].name == "lookup_weather"
    assert first.tools[0].parameters["properties"]["city"]["description"] == "City name."
    assert first.temperature == 0.3
    assert [m.role for m in second.messages] == ["user", "assistant", "tool"]
    assert second.messages[2].content == '{"sky": "sunny"}'
    assert [e for e, _ in events].count("usage") == 2
    assert (
        "llm_call",
        {
            "agent": "orchestrator",
            "route": "planner",
            "provider": "openrouter",
            "model": "openai/gpt-4o-mini",
        },
    ) in events


def test_saved_temperature_overrides_agent_default(fake_providers: FakeRegistry) -> None:
    configure_ai()
    from providers.models import AppSettings

    app = AppSettings.load()
    app.temperature = 0.9
    app.max_output_tokens = 1024
    app.save()
    with use_llm_resolver(services.make_resolver()):
        client = get_llm_client("script")
        client.models.generate_content(
            model=client.model_name,
            contents="Write a hook.",
            config=types.GenerateContentConfig(temperature=0.2),
        )
    request = fake_providers.get("openrouter").requests[0]
    assert request.temperature == 0.9
    assert request.max_output_tokens == 1024
