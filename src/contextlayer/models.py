"""Model IDs and providers used in the 3-stage extraction pipeline."""
from __future__ import annotations

import os

def get_provider() -> str:
    """Detect active LLM provider based on environment variables."""
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    elif os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "anthropic"

def get_model(stage: int) -> str:
    """Retrieve model name for given stage (1=Haiku, 2=Sonnet, 3=Opus) and provider."""
    provider = get_provider()
    if provider == "gemini":
        if stage == 1:
            return os.environ.get("CONTEXTLAYER_HAIKU_MODEL", "gemini-2.5-flash")
        elif stage == 2:
            return os.environ.get("CONTEXTLAYER_SONNET_MODEL", "gemini-2.5-pro")
        else:
            return os.environ.get("CONTEXTLAYER_OPUS_MODEL", "gemini-2.5-pro")
    elif provider == "openai":
        if stage == 1:
            return os.environ.get("CONTEXTLAYER_HAIKU_MODEL", "gpt-4o-mini")
        elif stage == 2:
            return os.environ.get("CONTEXTLAYER_SONNET_MODEL", "gpt-4o")
        else:
            return os.environ.get("CONTEXTLAYER_OPUS_MODEL", "o3-mini")
    else:  # anthropic
        if stage == 1:
            return os.environ.get("CONTEXTLAYER_HAIKU_MODEL", "claude-3-5-haiku-latest")
        elif stage == 2:
            return os.environ.get("CONTEXTLAYER_SONNET_MODEL", "claude-3-5-sonnet-latest")
        else:
            return os.environ.get("CONTEXTLAYER_OPUS_MODEL", "claude-3-opus-latest")

# Module level constants for backward compatibility
HAIKU_MODEL = get_model(1)
SONNET_MODEL = get_model(2)
OPUS_MODEL = get_model(3)
