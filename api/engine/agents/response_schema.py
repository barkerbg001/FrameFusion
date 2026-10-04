from typing import Any

from pydantic import BaseModel, ValidationError

from engine.llm import types


class StructuredOutputError(ValueError):
    """The model's reply still did not match the schema after one corrective retry."""

    def __init__(self, schema_name: str, problems: list[str]) -> None:
        super().__init__(
            f"The model's reply did not match {schema_name}: " + "; ".join(problems[:5])
        )
        self.problems = problems


def _strip_defaults(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _strip_defaults(value) for key, value in node.items() if key != "default"}
    if isinstance(node, list):
        return [_strip_defaults(item) for item in node]
    return node


def response_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return a provider-neutral JSON schema with property defaults removed."""
    return _strip_defaults(model.model_json_schema())


def validation_problems(exc: ValidationError) -> list[str]:
    """Field paths and messages only; pydantic's own text echoes the model's (long) input."""
    problems = []
    for error in exc.errors()[:8]:
        location = ".".join(str(part) for part in error["loc"])
        problems.append(f"{location}: {error['msg']}" if location else error["msg"])
    return problems


def _json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    return text


def generate_validated[M: BaseModel](
    client: Any,
    prompt: str,
    model: type[M],
    *,
    temperature: float | None,
    system: str | None = None,
    model_name: str | None = None,
    images: list[Any] | None = None,
) -> M:
    """Ask for JSON matching ``model``, retrying once on the same provider and model.

    The retry repeats the prompt with the validation problems, which fixes most
    omitted fields and truncated objects from models without strict schema support.
    ``images`` are ``types.ImagePart`` values sent with the prompt (multimodal models).
    """
    schema = response_schema(model)

    def with_images(text: str) -> Any:
        if not images:
            return text
        return [types.Content(role="user", parts=[types.Part(text=text), *images])]

    contents = with_images(prompt)
    for attempt in range(2):
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
                temperature=temperature,
            ),
        )
        try:
            return model.model_validate_json(_json_text(response.text or ""))
        except ValidationError as exc:
            problems = validation_problems(exc)
            if attempt:
                raise StructuredOutputError(model.__name__, problems) from exc
            contents = with_images(
                f"{prompt}\n\nYour previous reply did not match the required JSON schema:\n- "
                + "\n- ".join(problems)
                + "\nReply with one complete JSON object that includes every required field."
            )
    raise AssertionError("unreachable")
