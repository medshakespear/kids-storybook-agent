"""Provider configuration and safe, bounded API error handling."""
from __future__ import annotations

import os
import re
from openai import OpenAI

TEXT_PROVIDERS = {
    "gemini": ("GEMINI_API_KEY", "GEMINI_TEXT_MODEL", "gemini-3.5-flash-lite",
               "https://generativelanguage.googleapis.com/v1beta/openai/"),
    "openai": ("OPENAI_API_KEY", "OPENAI_TEXT_MODEL", "gpt-4.1-mini",
               "https://api.openai.com/v1"),
}


class ProviderError(RuntimeError):
    """A sanitized provider failure, with a retry decision."""

    def __init__(self, message: str, retryable: bool = False) -> None:
        """Store a safe message and whether another request may succeed."""
        super().__init__(message)
        self.retryable = retryable


def text_provider_names() -> list[str]:
    """Select one provider; retired Groq/fallback environment variables are ignored."""
    primary = os.getenv("TEXT_PROVIDER", "gemini").strip().lower()
    if primary not in TEXT_PROVIDERS:
        raise ValueError("TEXT_PROVIDER must be gemini or openai; Groq is no longer supported")
    names = [primary]
    for name in names:
        key = TEXT_PROVIDERS[name][0]
        if not os.getenv(key, "").strip():
            raise ValueError(f"{key} is required for {name}")
    return names


def text_client(name: str) -> tuple[OpenAI, str]:
    """Build an OpenAI-compatible client pointed only at the selected provider."""
    key, model_env, default_model, base_url = TEXT_PROVIDERS[name]
    model = os.getenv(model_env, default_model).strip()
    if name == "gemini":
        model = model.removeprefix("models/")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", model):
        raise ValueError(f"{model_env} must contain a model ID, without quotes or spaces")
    return OpenAI(api_key=os.environ[key].strip(), base_url=base_url, timeout=120,
                  max_retries=0), model


def image_provider_name() -> str:
    """Validate image configuration before any story tokens are spent."""
    provider = os.getenv("IMAGE_PROVIDER", "cloudflare").strip().lower()
    if provider == "cloudflare":
        if not os.getenv("CLOUDFLARE_API_TOKEN", "").strip():
            raise ValueError("CLOUDFLARE_API_TOKEN is required")
        if not re.fullmatch(r"[a-fA-F0-9]{32}", os.getenv("CLOUDFLARE_ACCOUNT_ID", "")):
            raise ValueError("CLOUDFLARE_ACCOUNT_ID must be the 32-character account ID")
        steps = int(os.getenv("CLOUDFLARE_IMAGE_STEPS", "4"))
        if not 1 <= steps <= 8:
            raise ValueError("CLOUDFLARE_IMAGE_STEPS must be between 1 and 8")
    elif provider == "openai":
        if not os.getenv("OPENAI_API_KEY", "").strip():
            raise ValueError("OPENAI_API_KEY is required for OpenAI images")
    else:
        raise ValueError("IMAGE_PROVIDER must be cloudflare or openai")
    return provider


def validate_providers() -> None:
    """Check all required credentials without making network requests."""
    text_provider_names()
    image_provider_name()


def safe_api_error(provider: str, exc: Exception, model: str | None = None) -> ProviderError:
    """Avoid leaking response bodies, prompts, or credentials in logs."""
    if isinstance(exc, ProviderError):
        return exc
    status = getattr(exc, "status_code", None)
    code = getattr(exc, "code", None)
    if status == 404:
        model_env = TEXT_PROVIDERS.get(provider, (None, "model setting"))[1]
        selected = f" for model {model!r}" if model else ""
        return ProviderError(
            f"{provider}: HTTP 404{selected}; model or endpoint unavailable to this account. "
            f"Check {model_env} against the provider model catalog. "
            "Railway model variables override code defaults."
        )
    if status == 429:
        return ProviderError(f"{provider}: rate limit or quota reached; check your provider dashboard.",
                             code not in {"insufficient_quota", "credit_balance_exhausted"})
    if status in {401, 403}:
        return ProviderError(f"{provider}: authentication or permission denied; check its API key and access.")
    if status is not None:
        return ProviderError(f"{provider}: HTTP {status}; check model availability and provider settings.",
                             status in {408, 409} or status >= 500)
    return ProviderError(f"{provider}: request failed ({type(exc).__name__}).", True)
