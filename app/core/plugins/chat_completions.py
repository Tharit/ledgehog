"""What every client of an OpenAI-compatible chat-completions endpoint shares (architecture §5.4):
the URL from the configured endpoint, the Bearer key, the reasoning-effort field."""

from __future__ import annotations

from typing import Any


def chat_url(endpoint: str) -> str:
    """The endpoint's base (`http://host/v1`) or its full chat URL, as the chat-completions URL."""
    base = endpoint.rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def auth_headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def reasoning_field(effort: str | None) -> dict[str, Any]:
    """llama.cpp documents `reasoning_effort` as a top-level field, passed on to the model's template;
    nothing is sent where none is configured."""
    return {"reasoning_effort": effort} if effort is not None else {}
