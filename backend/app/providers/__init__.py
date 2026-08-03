"""Model providers.

Selected by `LLM_PROVIDER` (anthropic | openai | gemini). SDKs are imported lazily, so
only the provider actually in use needs to be installed.
"""

import functools

import structlog

from app.core.config import settings
from app.providers.base import (
    ChatProvider,
    ProviderCallFailed,
    ProviderError,
    ProviderEvent,
    TextChunk,
    ToolCall,
    ToolCallStarted,
    ToolResult,
    ToolSpec,
    Turn,
    TurnFinished,
)

logger = structlog.get_logger()

SUPPORTED = ("anthropic", "openai", "gemini")

# Per-million-token prices, used for the spend meter. Keyed by provider so the cost
# figure stays auditable rather than a constant buried in a handler.
PRICING: dict[str, tuple[float, float]] = {
    "anthropic": (3.00, 15.00),
    "openai": (2.00, 8.00),
    "gemini": (1.25, 10.00),
}


def _build(provider: str) -> ChatProvider:
    if provider == "anthropic":
        from app.providers.anthropic_provider import DEFAULT_MODEL, AnthropicProvider

        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.llm_model or DEFAULT_MODEL,
        )

    if provider == "openai":
        from app.providers.openai_provider import DEFAULT_MODEL, OpenAIProvider

        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.llm_model or DEFAULT_MODEL,
        )

    if provider == "gemini":
        from app.providers.gemini_provider import DEFAULT_MODEL, GeminiProvider

        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.llm_model or DEFAULT_MODEL,
        )

    raise ProviderError(
        f"Unknown LLM_PROVIDER {provider!r}. Supported: {', '.join(SUPPORTED)}"
    )


@functools.lru_cache(maxsize=1)
def get_provider() -> ChatProvider:
    """The configured provider. Built once; clients hold connection pools."""
    provider = _build(settings.llm_provider)
    logger.info("provider_ready", provider=provider.name, model=provider.model)
    return provider


def reset_provider_cache() -> None:
    """Drop the cached provider. Used by tests that swap configuration."""
    get_provider.cache_clear()


def pricing_for(provider: str) -> tuple[float, float]:
    """(input, output) dollars per million tokens, defaulting to the priciest known."""
    return PRICING.get(provider, (3.00, 15.00))


__all__ = [
    "PRICING",
    "SUPPORTED",
    "ChatProvider",
    "ProviderCallFailed",
    "ProviderError",
    "ProviderEvent",
    "TextChunk",
    "ToolCall",
    "ToolCallStarted",
    "ToolResult",
    "ToolSpec",
    "Turn",
    "TurnFinished",
    "get_provider",
    "pricing_for",
    "reset_provider_cache",
]
