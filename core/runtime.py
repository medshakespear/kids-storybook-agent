"""Small bounded settings and ordered concurrency helpers for generation stages."""
import os
from concurrent.futures import ThreadPoolExecutor, as_completed


def int_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read a bounded integer without exposing environment values in errors."""
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f'{name} must be an integer from {minimum} to {maximum}') from None
    if not minimum <= value <= maximum:
        raise ValueError(f'{name} must be from {minimum} to {maximum}')
    return value


def ordered_parallel(function, items, workers: int):
    """Run bounded independent work, preserve order, and cancel queued work on failure."""
    items = list(items)
    if workers == 1 or len(items) < 2:
        return [function(item) for item in items]
    executor = ThreadPoolExecutor(max_workers=min(workers, len(items)))
    futures = {executor.submit(function, item): index for index, item in enumerate(items)}
    results = [None] * len(items)
    try:
        for future in as_completed(futures):
            results[futures[future]] = future.result()
        return results
    finally:
        # In-flight calls finish within their request timeout; queued calls are cancelled.
        executor.shutdown(wait=True, cancel_futures=True)
