"""Bounded credential failover with thread-safe, process-local cooldowns."""
from __future__ import annotations

import logging
import math
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, TypeVar
from core.runtime import int_setting

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


class ProviderError(RuntimeError):
    """A sanitized failure with separate retry and credential-failover decisions."""

    def __init__(self, message: str, retryable: bool = False, *,
                 status_code: int | None = None, rotate: bool = False,
                 retry_after: float | None = None) -> None:
        """Keep routing metadata without retaining provider response bodies."""
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.rotate = rotate
        self.retry_after = retry_after


@dataclass(frozen=True)
class Credential:
    """One named slot; sensitive values are excluded from its representation."""

    label: str
    api_key: str = field(repr=False)
    account_id: str = field(default="", repr=False)
    quota_group: str = field(default="", repr=False)


def retry_after_seconds(headers=None, body=None) -> float | None:
    """Read Retry-After or Google's structured RetryInfo without logging a body."""
    delays = []
    value = (headers.get("retry-after") or headers.get("Retry-After")) if headers is not None else None
    if isinstance(value, str):
        try:
            delays.append(float(value))
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                delays.append((date - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
    if isinstance(body, dict):
        error = body.get("error", body)
        details = error.get("details", []) if isinstance(error, dict) else []
        for detail in details if isinstance(details, list) else []:
            if not isinstance(detail, dict) or detail.get("@type") != "type.googleapis.com/google.rpc.RetryInfo":
                continue
            delay = detail.get("retryDelay")
            try:
                if isinstance(delay, str) and delay.endswith("s"):
                    delays.append(float(delay[:-1]))
                elif isinstance(delay, dict):
                    delays.append(float(delay.get("seconds", 0)) + float(delay.get("nanos", 0)) / 1e9)
            except (ValueError, TypeError, OverflowError):
                pass
    valid = [delay for delay in delays if math.isfinite(delay) and delay >= 0]
    return max(valid) if valid else None


class CredentialPool:
    """Keep a healthy slot; fail over after quota, auth, or repeated transient errors."""

    def __init__(self, provider: str, credentials: tuple[Credential, ...], cooldown: float) -> None:
        """Initialize a pool without contacting any external service."""
        if not credentials:
            raise ValueError(f"No credentials configured for {provider}")
        self.provider = provider
        self.credentials = credentials
        self.cooldown = cooldown
        self._blocked_until = [0.0] * len(credentials)
        self._cursor = 0
        self._lock = threading.Lock()

    def _select(self, attempted: set[int]) -> int | None:
        """Choose an eligible slot under the lock; never wait while holding it."""
        with self._lock:
            now = time.monotonic()
            for offset in range(len(self.credentials)):
                index = (self._cursor + offset) % len(self.credentials)
                if index not in attempted and self._blocked_until[index] <= now:
                    self._cursor = index
                    return index
        return None

    def _block(self, index: int, error: ProviderError) -> None:
        """Apply quota cooldowns to known shared groups and disable rejected keys."""
        with self._lock:
            until = (math.inf if error.status_code in {401, 403}
                     else time.monotonic() + max(self.cooldown, error.retry_after or 0))
            group = self.credentials[index].quota_group
            for other, credential in enumerate(self.credentials):
                if other == index or (error.status_code == 429 and group and credential.quota_group == group):
                    self._blocked_until[other] = max(self._blocked_until[other], until)
            self._cursor = (index + 1) % len(self.credentials)

    def _exhausted(self, failures: list[str]) -> ProviderError:
        """Explain exhaustion without exposing tokens, account IDs, or response bodies."""
        with self._lock:
            earliest = min(self._blocked_until)
        if math.isfinite(earliest):
            wait = max(1, math.ceil(earliest - time.monotonic()))
            hint = f"Retry in at least {wait} seconds; provider limits or outages may require longer."
        else:
            hint = "All configured credentials were rejected; check keys and permissions, then restart."
        details = (" " + "; ".join(failures)) if failures else ""
        # Non-retryable here prevents the caller's content-repair loop from hammering the pool.
        return ProviderError(f"{self.provider}: no credential slots available. {hint}{details}")

    def run(self, operation: Callable[[Credential], T], *, deadline: float | None = None) -> T:
        """Visit each slot once with bounded transient retries and an optional deadline."""
        attempted, failures = set(), []
        attempts = int_setting('GEMINI_TRANSIENT_ATTEMPTS', 2, 1, 3) if self.provider == 'gemini' else 2
        while (index := self._select(attempted)) is not None:
            attempted.add(index)
            credential = self.credentials[index]
            for attempt in range(attempts):
                if deadline is not None and time.monotonic() >= deadline:
                    raise ProviderError(f'{self.provider}: request retry time budget exhausted; retry later.')
                try:
                    result = operation(credential)
                    LOGGER.info("%s: using %s", self.provider, credential.label)
                    return result
                except ProviderError as error:
                    if not error.rotate:
                        raise
                    transient = error.retryable and error.status_code not in {401, 403, 429}
                    if transient and attempt < attempts - 1 and (error.retry_after or 0) <= 10:
                        delay = max(2 ** (attempt + 1) + random.random(), error.retry_after or 0)
                        if deadline is not None and time.monotonic() + delay >= deadline:
                            self._block(index, error)
                            raise ProviderError(f'{self.provider}: request retry time budget exhausted; retry later.') from None
                        LOGGER.warning("%s: %s; retrying this slot in %.1fs (%s/%s)",
                                       credential.label, error, delay, attempt + 2, attempts)
                        time.sleep(delay)
                        with self._lock:
                            ready = self._blocked_until[index] <= time.monotonic()
                        if ready:
                            continue
                    # Do not block the worker on a long Retry-After or permanently
                    # disable a key just because its provider had a temporary outage.
                    self._block(index, error)
                    failure = f"{credential.label}: {error}"
                    failures.append(failure)
                    LOGGER.warning("%s; trying the next available slot", failure)
                    break
        raise self._exhausted(failures) from None


_POOLS: dict[str, tuple[tuple, CredentialPool]] = {}
_REGISTRY_LOCK = threading.Lock()


def credential_pool(provider: str, credentials: tuple[Credential, ...], cooldown: float = 60) -> CredentialPool:
    """Reuse cooldowns across pages/books/threads until configuration or process changes."""
    signature = (credentials, cooldown)
    with _REGISTRY_LOCK:
        existing = _POOLS.get(provider)
        if existing is None or existing[0] != signature:
            _POOLS[provider] = (signature, CredentialPool(provider, credentials, cooldown))
        return _POOLS[provider][1]


def reset_credential_pools() -> None:
    """Reset process-local routing state, primarily for isolated offline tests."""
    with _REGISTRY_LOCK:
        _POOLS.clear()
