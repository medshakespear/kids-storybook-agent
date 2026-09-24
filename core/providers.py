"""Provider configuration and safe, bounded API error handling."""
from __future__ import annotations

import os
import re
import time
from types import SimpleNamespace
from openai import APIConnectionError, OpenAI
from core.credential_pool import Credential, ProviderError, credential_pool, retry_after_seconds
from core.runtime import int_setting

TEXT_PROVIDERS = {
    "gemini": ("GEMINI_API_KEY", "GEMINI_TEXT_MODEL", "gemini-3.5-flash-lite",
               "https://generativelanguage.googleapis.com/v1beta/openai/"),
    "openai": ("OPENAI_API_KEY", "OPENAI_TEXT_MODEL", "gpt-4.1-mini",
               "https://api.openai.com/v1"),
}


def configured_credentials(provider: str) -> tuple[Credential, ...]:
    """Read up to four slots, treating legacy unnumbered variables as slot one."""
    credentials, seen = [], set()
    key_base = "GEMINI_API_KEY" if provider == "gemini" else "CLOUDFLARE_API_TOKEN"
    if provider not in {"gemini", "cloudflare"}:
        raise ValueError("Credential pools support gemini and cloudflare")
    for slot in range(1, 5):
        key = os.getenv(f"{key_base}_{slot}", "").strip()
        if slot == 1 and not key:
            key = os.getenv(key_base, "").strip()
        account = ""
        group = ""
        if provider == "cloudflare":
            explicit_account = os.getenv(f"CLOUDFLARE_ACCOUNT_ID_{slot}", "").strip()
            if not key and explicit_account:
                raise ValueError(f"{key_base}_{slot} is required with CLOUDFLARE_ACCOUNT_ID_{slot}")
            if key:
                account = explicit_account or os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
                if not re.fullmatch(r"[a-fA-F0-9]{32}", account):
                    raise ValueError(f"CLOUDFLARE_ACCOUNT_ID_{slot} (or CLOUDFLARE_ACCOUNT_ID) must be the 32-character account ID")
                account = account.lower()
                group = account
        else:
            group = os.getenv(f"GEMINI_PROJECT_ID_{slot}", "").strip()
            if slot == 1 and not group:
                group = os.getenv("GEMINI_PROJECT_ID", "").strip()
        identity = (key, account)
        if key and identity not in seen:
            seen.add(identity)
            credentials.append(Credential(f"{provider} slot {slot}", key, account, group))
    if not credentials:
        raise ValueError(f"{key_base}_1 (or {key_base}) is required for {provider}")
    return tuple(credentials)


def get_provider_pool(provider: str):
    """Validate cooldown configuration and return a shared, secret-safe pool."""
    try:
        cooldown = int(os.getenv("API_KEY_COOLDOWN_SECONDS", "60"))
    except ValueError:
        raise ValueError("API_KEY_COOLDOWN_SECONDS must be an integer between 1 and 86400") from None
    if not 1 <= cooldown <= 86400:
        raise ValueError("API_KEY_COOLDOWN_SECONDS must be between 1 and 86400")
    return credential_pool(provider, configured_credentials(provider), cooldown)


class GeminiPoolClient:
    """Expose the synchronous chat interface used by all text-generation modules."""

    def __init__(self, base_url: str, model: str) -> None:
        """Validate configuration once; actual SDK clients are opened on demand."""
        self.base_url = base_url
        self.model = model
        self.pool = get_provider_pool("gemini")
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self._closed = False

    def create(self, **kwargs):
        """Retry the same completion on another available key after a limit error."""
        if self._closed:
            raise RuntimeError("Text client is closed")
        deadline = time.monotonic() + int_setting('GEMINI_CALL_BUDGET_SECONDS', 180, 30, 300)
        timeout = int_setting('GEMINI_REQUEST_TIMEOUT_SECONDS', 40, 10, 120)

        def request(credential):
            """Close every SDK transport, including those returning errors."""
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderError('gemini: request retry time budget exhausted; retry later.', True)
            api = OpenAI(api_key=credential.api_key, base_url=self.base_url,
                         timeout=min(timeout, remaining), max_retries=0)
            try:
                return api.chat.completions.create(**kwargs)
            except Exception as exc:
                raise safe_api_error("gemini", exc, model=self.model) from None
            finally:
                api.close()

        return self.pool.run(request, deadline=deadline)

    def close(self) -> None:
        """Close the facade; transports are already closed after each request."""
        self._closed = True


def text_provider_names() -> list[str]:
    """Select one provider; retired Groq/fallback environment variables are ignored."""
    primary = os.getenv("TEXT_PROVIDER", "gemini").strip().lower()
    if primary not in TEXT_PROVIDERS:
        raise ValueError("TEXT_PROVIDER must be gemini or openai; Groq is no longer supported")
    names = [primary]
    for name in names:
        if name == "gemini":
            get_provider_pool(name)
            continue
        key = TEXT_PROVIDERS[name][0]
        if not os.getenv(key, "").strip():
            raise ValueError(f"{key} is required for {name}")
    return names


def text_worker_limit(requested: int) -> int:
    """Serialize Gemini work so one sticky key serves the entire book."""
    if requested < 1:
        raise ValueError("requested text workers must be positive")
    provider = text_provider_names()[0]
    if provider == "gemini":
        return 1
    return requested


def text_client(name: str) -> tuple[OpenAI | GeminiPoolClient, str]:
    """Build an OpenAI-compatible client pointed only at the selected provider."""
    key, model_env, default_model, base_url = TEXT_PROVIDERS[name]
    model = os.getenv(model_env, default_model).strip()
    if name == "gemini":
        model = model.removeprefix("models/")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", model):
        raise ValueError(f"{model_env} must contain a model ID, without quotes or spaces")
    if name == "gemini":
        return GeminiPoolClient(base_url, model), model
    return OpenAI(api_key=os.environ[key].strip(), base_url=base_url, timeout=120,
                  max_retries=0), model


def image_provider_name() -> str:
    """Validate image configuration before any story tokens are spent."""
    provider = os.getenv("IMAGE_PROVIDER", "cloudflare").strip().lower()
    if provider == "cloudflare":
        get_provider_pool(provider)
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
    response = getattr(exc, "response", None)
    delay = retry_after_seconds(getattr(response, "headers", None), getattr(exc, "body", None))
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
                             code not in {"insufficient_quota", "credit_balance_exhausted"},
                             status_code=429, rotate=provider == "gemini", retry_after=delay)
    if status in {401, 403}:
        return ProviderError(f"{provider}: authentication or permission denied; check its API key and access.",
                             status_code=status, rotate=False)
    if status is not None:
        if status in {408, 409} or 500 <= status <= 599:
            hint = ("service temporarily unavailable or overloaded" if status == 503
                    else "temporary server or request failure")
            return ProviderError(f"{provider}: HTTP {status}; {hint}. Retry later if all slots fail.",
                                 True, status_code=status, rotate=False, retry_after=delay)
        return ProviderError(f"{provider}: HTTP {status}; check model availability and provider settings.",
                             status_code=status)
    if isinstance(exc, APIConnectionError):
        return ProviderError(f"{provider}: temporary connection failure or timeout.",
                             True, rotate=False)
    return ProviderError(f"{provider}: request failed ({type(exc).__name__}).", True)
