"""Provider client registry."""

from .anthropic_client import AnthropicClient
from .base import ConnectionResult, ModelInfo, ProviderClient, ProviderInfo, redact
from .gemini import GeminiClient
from .openrouter import OpenRouterClient

CLIENTS: dict[str, type[ProviderClient]] = {
    "openrouter": OpenRouterClient,
    "gemini": GeminiClient,
    "anthropic": AnthropicClient,
}

__all__ = [
    "CLIENTS",
    "AnthropicClient",
    "ConnectionResult",
    "GeminiClient",
    "ModelInfo",
    "OpenRouterClient",
    "ProviderClient",
    "ProviderInfo",
    "redact",
]
