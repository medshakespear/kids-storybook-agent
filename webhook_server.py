"""Flask web service for on-demand storybook generation."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_from_directory, url_for

from core.paths import OUTPUT_DIR, ensure_runtime_directories
from core.pipeline import generate_book, load_grade_config
from core.state_manager import load_state
from core.theme_picker import build_webhook_inspiration, pick_webhook_grade_band


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)
ensure_runtime_directories()


def _authorized() -> bool:
    """Validate the optional webhook API key."""

    expected = os.environ.get("WEBHOOK_API_KEY")
    return not expected or request.headers.get("X-API-Key") == expected


@app.get("/health")
def health() -> tuple[dict[str, str], int]:
    """Return service health for Railway checks."""

    return {"status": "ok"}, 200


@app.post("/generate")
def generate() -> tuple[object, int] | object:
    """Generate one original book from a URL-derived inspiration seed."""

    if not _authorized():
        return jsonify({"error": "Unauthorized. Supply a valid X-API-Key header."}), 401
    if not request.is_json:
        return jsonify({"error": "Request body must be JSON."}), 415
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    link = payload.get("link")
    if not isinstance(link, str) or len(link) > 2048:
        return jsonify({"error": "link is required and must be a URL string."}), 400
    parsed = urlparse(link)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return jsonify({"error": "link must be a valid http or https URL."}), 400

    try:
        grade_config = load_grade_config()
        grade_band = payload.get("grade_band") or pick_webhook_grade_band(load_state())
        if grade_band not in grade_config:
            return jsonify(
                {
                    "error": "Unknown grade_band.",
                    "allowed_grade_bands": list(grade_config),
                }
            ), 400
        inspiration = build_webhook_inspiration(link)
        broad_theme = (
            "An original classroom-friendly story inspired only by the broad educational "
            "niche words contained in the supplied URL"
        )
        story, pdf_path = generate_book(
            theme=broad_theme,
            grade_band=grade_band,
            source_context=inspiration,
            grade_config=grade_config,
        )
        download_url = url_for(
            "download_output", filename=pdf_path.name, _external=True
        )
        return jsonify(
            {
                "status": "completed",
                "title": story["title"],
                "grade_band": grade_band,
                "pdf_path": f"/output/{pdf_path.name}",
                "download_url": download_url,
            }
        )
    except Exception as exc:
        logger.exception("On-demand generation failed")
        return jsonify(
            {
                "error": "Storybook generation failed.",
                "detail": str(exc),
            }
        ), 500


@app.get("/output/<path:filename>")
def download_output(filename: str) -> object:
    """Serve a generated PDF from the ephemeral Railway filesystem."""

    if not filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are available."}), 404
    return send_from_directory(Path(OUTPUT_DIR).resolve(), filename, as_attachment=True)


@app.errorhandler(413)
def request_too_large(_: Exception) -> tuple[object, int]:
    """Return JSON when a request exceeds the configured limit."""

    return jsonify({"error": "Request body is too large."}), 413


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)

