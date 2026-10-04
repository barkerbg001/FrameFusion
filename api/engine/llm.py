"""Provider-neutral LLM layer used by every FrameFusion agent.

Agents call ``get_llm_client(agent_id)`` and then
``client.models.generate_content(model=..., contents=..., config=...)``.
The Django layer installs a resolver (per request or per background job) that
maps the agent to its model route and then to the provider, model and
credentials configured in Settings. Model routes are about cost and capability
only; they are unrelated to the orchestrator's personality. Nothing here falls
back to a different provider: if the configured one is unavailable, the call fails.
"""

from __future__ import annotations

import contextvars
import inspect
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Literal, Protocol, get_args, get_origin

from engine.runtime import RunCancelled, check_cancelled, report

Route = Literal["planner", "production"]

ROUTE_LABELS: dict[Route, str] = {
    "planner": "Orchestrator and writing",
    "production": "Visual specialist",
}

AGENT_ROUTES: dict[str, Route] = {
    "orchestrator": "planner",
    "research": "planner",
    "script": "planner",
    "ideas": "planner",
    "visual": "production",
    "music_composer": "production",
}


def route_for(agent_id: str) -> Route:
    try:
        return AGENT_ROUTES[agent_id]
    except KeyError as exc:
        raise ValueError(f"Unknown agent id: {agent_id}") from exc


ErrorKind = Literal[
    "not_configured",
    "encryption_unavailable",
    "invalid_credentials",
    "permission_denied",
    "rate_limited",
    "quota_exceeded",
    "model_unavailable",
    "bad_request",
    "timeout",
    "network",
    "provider_error",
    "unsupported",
]


class LLMError(Exception):
    """Normalized provider failure. Messages never contain credentials."""

    def __init__(
        self,
        message: str,
        *,
        kind: ErrorKind = "provider_error",
        provider: str | None = None,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after = retry_after
        self.request_id = request_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "provider": self.provider,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "retry_after": self.retry_after,
            "request_id": self.request_id,
        }


class LLMConfigurationError(LLMError):
    def __init__(self, message: str, *, kind: ErrorKind = "not_configured", **kwargs: Any):
        super().__init__(message, kind=kind, **kwargs)


# --- Normalized request/response types ------------------------------------------------


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    function: Callable[..., Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    raw: Any = None


@dataclass
class CompletionRequest:
    model: str
    messages: list[Message]
    system: str | None = None
    tools: list[ToolSpec] = field(default_factory=list)
    response_schema: dict[str, Any] | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None


@dataclass
class CompletionResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_assistant: Any = None
    provider: str = ""
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None


class ChatProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def label(self) -> str: ...

    def complete(self, request: CompletionRequest) -> CompletionResult: ...


@dataclass
class LLMBinding:
    provider: ChatProvider
    model: str
    route: Route
    temperature: float | None = None
    max_output_tokens: int | None = None


Resolver = Callable[[str], LLMBinding]

_resolver: contextvars.ContextVar[Resolver | None] = contextvars.ContextVar(
    "framefusion_llm_resolver", default=None
)


@contextmanager
def use_llm_resolver(resolver: Resolver) -> Iterator[None]:
    token = _resolver.set(resolver)
    try:
        yield
    finally:
        _resolver.reset(token)


def resolve_binding(agent_id: str) -> LLMBinding:
    resolver = _resolver.get()
    if resolver is None:
        raise LLMConfigurationError(
            "No AI provider is configured for this request. "
            "Add an API key in Settings → AI providers."
        )
    return resolver(agent_id)


# --- Agent-facing compatibility types ----------------------------------------------------


@dataclass
class Content:
    role: str
    parts: list[Any]


@dataclass
class Part:
    text: str


@dataclass
class AutomaticFunctionCallingConfig:
    maximum_remote_calls: int = 16


@dataclass
class FunctionCallingConfig:
    mode: str = "AUTO"


@dataclass
class ToolConfig:
    function_calling_config: FunctionCallingConfig


@dataclass
class GenerateContentConfig:
    system_instruction: str | None = None
    tools: list[Callable[..., Any]] | None = None
    temperature: float | None = None
    response_mime_type: str | None = None
    response_schema: dict[str, Any] | None = None
    automatic_function_calling: AutomaticFunctionCallingConfig | None = None
    tool_config: ToolConfig | None = None


types = SimpleNamespace(
    Content=Content,
    Part=Part,
    GenerateContentConfig=GenerateContentConfig,
    AutomaticFunctionCallingConfig=AutomaticFunctionCallingConfig,
    FunctionCallingConfig=FunctionCallingConfig,
    ToolConfig=ToolConfig,
)


_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _annotation_schema(annotation: Any) -> dict[str, Any]:
    if isinstance(annotation, str):
        annotation = {"str": str, "int": int, "float": float, "bool": bool}.get(annotation, str)
    origin = get_origin(annotation)
    if origin is not None and type(None) in get_args(annotation):
        values = [item for item in get_args(annotation) if item is not type(None)]
        return _annotation_schema(values[0]) if values else {"type": "string"}
    return {"type": _JSON_TYPES.get(annotation, "string")}


def _parse_docstring_args(doc: str) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    in_args = False
    current: str | None = None
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped == "Args:":
            in_args = True
            continue
        if in_args and stripped in ("Returns:", "Raises:"):
            break
        if not in_args or not stripped:
            continue
        name, sep, rest = stripped.partition(":")
        if sep and name.isidentifier() and not line.startswith(" " * 8):
            current = name
            descriptions[current] = rest.strip()
        elif current:
            descriptions[current] = f"{descriptions[current]} {stripped}".strip()
    return descriptions


def tool_spec(function: Callable[..., Any]) -> ToolSpec:
    signature = inspect.signature(function)
    doc = inspect.getdoc(function) or ""
    arg_docs = _parse_docstring_args(doc)
    properties: dict[str, Any] = {}
    for name, parameter in signature.parameters.items():
        schema = _annotation_schema(parameter.annotation)
        if name in arg_docs:
            schema["description"] = arg_docs[name]
        properties[name] = schema
    required = [
        name
        for name, parameter in signature.parameters.items()
        if parameter.default is inspect.Parameter.empty
    ]
    summary = doc.split("\n\n", 1)[0].strip()
    return ToolSpec(
        name=function.__name__,
        description=summary or function.__name__,
        parameters={
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        function=function,
    )


def _coerce_arguments(function: Callable[..., Any], arguments: dict[str, Any]) -> dict[str, Any]:
    signature = inspect.signature(function)
    coerced: dict[str, Any] = {}
    for name, value in arguments.items():
        parameter = signature.parameters.get(name)
        if parameter is None:
            continue
        expected = _annotation_schema(parameter.annotation)["type"]
        try:
            if expected == "integer" and not isinstance(value, bool):
                value = int(float(value))
            elif expected == "number" and not isinstance(value, bool):
                value = float(value)
            elif expected == "string" and not isinstance(value, str):
                value = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        except (TypeError, ValueError):
            pass
        coerced[name] = value
    return coerced


def _run_tool(spec: ToolSpec | None, call: ToolCall) -> str:
    if spec is None:
        return json.dumps({"error": f"Unknown tool: {call.name}"})
    try:
        result = spec.function(**_coerce_arguments(spec.function, call.arguments))
    except (RunCancelled, LLMError):
        raise
    except TypeError as exc:
        return json.dumps({"error": f"Invalid arguments for {call.name}: {exc}"})
    except Exception as exc:  # tools already record their own failures
        if getattr(exc, "abort_run", False):
            raise
        return json.dumps({"error": str(exc)})
    return result if isinstance(result, str) else json.dumps(result)


def _to_messages(contents: Any) -> list[Message]:
    if isinstance(contents, str):
        return [Message(role="user", content=contents)]
    messages: list[Message] = []
    for content in contents:
        text = "".join(getattr(part, "text", "") or "" for part in content.parts)
        if content.role in ("model", "assistant"):
            messages.append(Message(role="assistant", content=text))
        else:
            messages.append(Message(role="user", content=text))
    return messages


class LLMClient:
    def __init__(self, agent_id: str, binding: LLMBinding) -> None:
        self.agent_id = agent_id
        self.binding = binding
        self.models = SimpleNamespace(generate_content=self.generate_content)

    @property
    def model_name(self) -> str:
        return self.binding.model

    def generate_content(
        self,
        *,
        model: str | None = None,
        contents: Any,
        config: GenerateContentConfig | None = None,
    ) -> SimpleNamespace:
        config = config or GenerateContentConfig()
        binding = self.binding
        specs = [tool_spec(function) for function in config.tools or []]
        by_name = {spec.name: spec for spec in specs}
        max_calls = (
            config.automatic_function_calling.maximum_remote_calls
            if config.automatic_function_calling
            else 16
        )
        temperature = binding.temperature if binding.temperature is not None else config.temperature
        messages = _to_messages(contents)
        selected_model = model or binding.model

        report(
            "llm_call",
            agent=self.agent_id,
            route=binding.route,
            provider=binding.provider.name,
            model=selected_model,
        )

        for _ in range(max_calls + 1):
            check_cancelled()
            result = binding.provider.complete(
                CompletionRequest(
                    model=selected_model,
                    messages=messages,
                    system=config.system_instruction,
                    tools=specs,
                    response_schema=config.response_schema,
                    temperature=temperature,
                    max_output_tokens=binding.max_output_tokens,
                )
            )
            report(
                "usage",
                agent=self.agent_id,
                provider=result.provider or binding.provider.name,
                model=result.model or selected_model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
            if not result.tool_calls:
                return SimpleNamespace(
                    text=result.text,
                    provider=result.provider,
                    model=result.model or selected_model,
                )
            messages.append(
                Message(
                    role="assistant",
                    content=result.text,
                    tool_calls=result.tool_calls,
                    raw=result.raw_assistant,
                )
            )
            for call in result.tool_calls:
                check_cancelled()
                messages.append(
                    Message(
                        role="tool",
                        content=_run_tool(by_name.get(call.name), call),
                        tool_call_id=call.id,
                        tool_name=call.name,
                    )
                )
        raise LLMError(
            f"The model requested more than {max_calls} tool calls without finishing.",
            kind="provider_error",
            provider=binding.provider.name,
        )


def get_llm_client(agent_id: str) -> LLMClient:
    route_for(agent_id)
    return LLMClient(agent_id, resolve_binding(agent_id))


def get_llm_model_name(agent_id: str) -> str:
    return resolve_binding(agent_id).model
