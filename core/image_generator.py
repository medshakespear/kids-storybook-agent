"""Generate page illustrations with Cloudflare or explicitly selected OpenAI."""
from __future__ import annotations

import base64
import io
import logging
import os
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from PIL import Image
from core.providers import ProviderError, get_provider_pool, image_provider_name, safe_api_error
from core.credential_pool import Credential, retry_after_seconds
from core.runtime import int_setting, ordered_parallel

STYLE_LOCK = (
    "Children's book illustration. Consistent warm teal, coral, golden yellow palette; "
    "soft matte rendering, clean outlines, gentle daylight. Same character proportions "
    "and clothing throughout. Center important action for portrait A4 cropping; keep "
    "faces away from edges. No text, letters, logos, signatures or watermarks."
)


def _image_prompt(story: dict, page: dict, style: str, limit: int = 2048) -> str:
    """Fit Cloudflare's prompt limit while retaining the full character description."""
    description = story["character_description"]
    lock = STYLE_LOCK
    if story.get('resource_type') == 'activity_pack':
        lock = ('Original educational illustration; follow the supplied pack palette and rendering style consistently. '
                'Use the cast only when people are requested. Isolated objects contain no people. '
                'No words, letters, numbers, logos, borders, labels or answer marks. '
                'One composition, no panels. Full subject visible with generous white margins, no cropping.')
        # Task-critical scene details (especially corrections near the end) must
        # never be truncated to make room for decorative style instructions.
        required = f"SCENE: {page['image_prompt']}\nCHARACTER: {description}\n{lock}\nSTYLE: "
        available = limit - len(required)
        if available < 0:
            raise ValueError('Scene and character requirements exceed the image prompt limit')
        return required + style[:available]
    prefix = f"CHARACTER: {description}\nSTYLE: {style}\n{lock}\nSCENE: "
    scene = page["image_prompt"].replace(description, "").strip(" .\n")
    available = limit - len(prefix)
    if available < 100:
        raise ValueError("Character and style descriptions are too long for the image provider")
    return prefix + scene[:available]


def _cloudflare_image(prompt: str) -> bytes:
    """Repeat the identical image request on the next available credential slot."""
    return get_provider_pool("cloudflare").run(lambda credential: _cloudflare_request(prompt, credential))


def _cloudflare_request(prompt: str, credential: Credential) -> bytes:
    """Request FLUX through the REST API and decode its JSON base64 result."""
    account = credential.account_id
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/black-forest-labs/flux-1-schnell"
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {credential.api_key}"},
            json={"prompt": prompt, "steps": int(os.getenv("CLOUDFLARE_IMAGE_STEPS", "4"))},
            timeout=(10, int_setting('IMAGE_REQUEST_TIMEOUT_SECONDS', 60, 15, 180)),
        )
    except requests.RequestException:
        raise ProviderError("Cloudflare: network request failed.", True) from None
    if response.status_code != 200:
        status = response.status_code
        delay = retry_after_seconds(response.headers)
        if status == 429:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            errors = payload.get("errors", []) if isinstance(payload, dict) else []
            if isinstance(errors, list) and any(isinstance(error, dict) and str(error.get("code")) == "3036" for error in errors):
                # Workers AI's daily neuron allocation resets at midnight UTC.
                now = datetime.now(timezone.utc)
                reset = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), timezone.utc)
                delay = max(delay or 0, (reset - now).total_seconds())
        hint = "quota/rate limit reached" if status == 429 else "check API token, permissions and account ID"
        raise ProviderError(f"Cloudflare: HTTP {status}; {hint}.", status >= 500 or status == 408,
                            status_code=status, rotate=status in {401, 403, 429}, retry_after=delay)
    try:
        payload = response.json()
        if payload.get("success") is not True:
            raise ProviderError("Cloudflare rejected the image request; check Workers AI dashboard.")
        return base64.b64decode(payload["result"]["image"], validate=True)
    except (ValueError, KeyError, TypeError):
        raise ProviderError("Cloudflare returned an invalid image response.", True) from None


def _openai_image(client: Any, prompt: str) -> bytes:
    """Retain the opt-in OpenAI image backend without automatic paid fallback."""
    result = client.images.generate(
        model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"), prompt=prompt,
        size="1024x1536", quality=os.getenv("OPENAI_IMAGE_QUALITY", "medium"), n=1,
    ).data[0]
    if result.b64_json:
        return base64.b64decode(result.b64_json, validate=True)
    if result.url:
        response = requests.get(result.url, timeout=(15, 120))
        response.raise_for_status()
        return response.content
    raise ProviderError("OpenAI returned no image.", True)


def _save_png(data: bytes, destination: Path) -> None:
    """Decode actual image bytes and normalize JPEG/PNG output to a valid PNG."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if min(image.size) < 256:
                raise ValueError("Image is too small")
            image.convert("RGB").save(destination, "PNG")
    except (OSError, ValueError):
        raise ProviderError("Provider returned corrupt or undersized image data.", True) from None


def generate_images(story: dict[str, Any], grade_band_config: dict[str, Any],
                    temp_dir: str | Path, *, client: Any = None,
                    max_retries: int = 2) -> list[Path]:
    """Generate each page with bounded retries, preserving one provider per book."""
    if max_retries < 1:
        raise ValueError("max_retries must be positive")
    provider = "openai" if client is not None else image_provider_name()
    api = client
    if provider == "openai" and api is None:
        from openai import OpenAI
        api = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=180, max_retries=0)
    destination_dir = Path(temp_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    def generate_page(page):
        """Generate one distinct asset without mutating shared page ordering."""
        prompt = _image_prompt(story, page, grade_band_config["illustration_style"])
        destination = destination_dir / f"page_{int(page['page_number']):02d}.png"
        for attempt in range(max_retries):
            try:
                data = _cloudflare_image(prompt) if provider == "cloudflare" else _openai_image(api, prompt)
                _save_png(data, destination)
                logging.getLogger(__name__).info("Illustration %s: %s", page['page_number'], provider)
                return destination
            except Exception as exc:
                destination.unlink(missing_ok=True)
                error = safe_api_error(provider, exc)
                if not error.retryable or attempt == max_retries - 1:
                    raise ImageGenerationError(f"Page {page['page_number']}: {error}") from None
                time.sleep(min(2 ** attempt + random.random(), 30))
    try:
        return ordered_parallel(generate_page, story['pages'],
                                1 if client is not None else int_setting('IMAGE_WORKERS', 3, 1, 4))
    finally:
        if api is not None and client is None:
            api.close()


class ImageGenerationError(RuntimeError):
    """An illustration could not be generated after bounded retries."""
