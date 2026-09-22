"""Generate and save one OpenAI illustration for every story page."""

from __future__ import annotations

import base64
import os
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openai import OpenAI


class ImageGenerationError(RuntimeError):
    """Raised when an illustration cannot be generated after retrying."""


def _save_image_result(image_data: Any, destination: Path) -> None:
    """Save either base64 image data or an API-hosted image URL."""

    encoded = getattr(image_data, "b64_json", None)
    url = getattr(image_data, "url", None)
    if encoded:
        destination.write_bytes(base64.b64decode(encoded))
        return
    if url:
        import requests

        response = requests.get(url, timeout=120)
        response.raise_for_status()
        destination.write_bytes(response.content)
        return
    raise ValueError("Image API response contained neither b64_json nor url.")


def generate_images(
    story: dict[str, Any],
    grade_band_config: dict[str, Any],
    temp_dir: str | Path,
    *,
    client: "OpenAI | None" = None,
    max_retries: int = 4,
) -> list[Path]:
    """Generate one visually consistent illustration for each story page."""

    destination_dir = Path(temp_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    if client is None:
        from openai import OpenAI

        openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    else:
        openai_client = client
    model = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
    quality = os.environ.get("OPENAI_IMAGE_QUALITY", "medium")
    band_style = grade_band_config["illustration_style"]
    style_lock = (
        "STYLE LOCK FOR THIS BOOK: cohesive children's publishing illustration; "
        "use the same color palette, character proportions, line quality, rendering "
        "technique, and lighting language on every page. Portrait composition suitable "
        "for A4. Keep important faces and action away from the outer 8% trim area. "
        "No text, letters, numbers, logos, signatures, borders, or watermarks."
    )

    paths: list[Path] = []
    for page in story["pages"]:
        page_number = int(page["page_number"])
        final_prompt = f"{band_style}\n\n{style_lock}\n\nSCENE: {page['image_prompt']}"
        destination = destination_dir / f"page_{page_number:02d}.png"
        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                result = openai_client.images.generate(
                    model=model,
                    prompt=final_prompt,
                    size="1024x1536",
                    quality=quality,
                    n=1,
                )
                _save_image_result(result.data[0], destination)
                if destination.stat().st_size < 1024:
                    raise ValueError("Generated image file was unexpectedly small.")
                paths.append(destination)
                break
            except Exception as exc:
                last_error = exc
                destination.unlink(missing_ok=True)
                if attempt < max_retries - 1:
                    time.sleep(min((2**attempt) + random.random(), 30))
        else:
            raise ImageGenerationError(
                f"Failed to generate illustration for page {page_number}: {last_error}"
            ) from last_error

    return paths
