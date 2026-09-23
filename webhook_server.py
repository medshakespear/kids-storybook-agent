"""Flask web service for on-demand classroom activity-pack generation."""

from __future__ import annotations

import logging
import json
import hmac
import os
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_from_directory, url_for, render_template

from core.book_library import list_books, register_book, receive_pdf
from core.paths import OUTPUT_DIR, ensure_runtime_directories
from core.pipeline import generate_book, load_grade_config
from core.state_manager import load_state
from core.theme_picker import build_webhook_inspiration, pick_webhook_grade_band


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
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
    """Generate an original pack from a teacher description, reference URL, or both."""

    if not _authorized():
        return jsonify({"error": "Unauthorized. Supply a valid X-API-Key header."}), 401
    if not request.is_json:
        return jsonify({"error": "Request body must be JSON."}), 415
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    link = payload.get("link")
    description = payload.get('description', '')
    if not isinstance(description, str) or len(description) > 4000:
        return jsonify(error='description must be text of at most 4000 characters.'), 400
    description = description.strip()
    if link is not None:
        if not isinstance(link, str) or len(link) > 2048:
            return jsonify(error='link must be a URL string.'), 400
        parsed = urlparse(link)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            return jsonify(error='link must be a valid http or https URL.'), 400
    if not link and not description:
        return jsonify(error='Provide a description or a reference link.'), 400

    try:
        grade_config = load_grade_config()
        grade_band = payload.get("grade_band") or pick_webhook_grade_band(load_state())
        if not isinstance(grade_band, str) or grade_band not in grade_config:
            return jsonify(
                {
                    "error": "Unknown grade_band.",
                    "allowed_grade_bands": list(grade_config),
                }
            ), 400
        inspiration = build_webhook_inspiration(link) if link else ''
        if description:
            inspiration += '\nTeacher creative brief: ' + description
        broad_theme = (
            "An original classroom exercise pack inspired only by the broad educational "
            "niche words contained in the supplied URL"
        )
        story, pdf_path = generate_book(
            theme=broad_theme,
            grade_band=grade_band,
            source_context=inspiration,
            grade_config=grade_config,
        )
        register_book(story, pdf_path.name, "On demand")
        download_url = url_for(
            "download_output", filename=pdf_path.name, _external=True
        )
        return jsonify(
            {
                "status": "completed",
                "title": story["title"],
                "resource_type": "activity_pack",
                "grade_band": grade_band,
                "pdf_path": f"/output/{pdf_path.name}",
                "download_url": download_url,
                "page_count": story.get("page_count"),
                "image_review": story.get("image_review"),
                "generation_seconds": story.get("generation_seconds"),
            }
        )
    except Exception as exc:
        logger.exception("On-demand generation failed")
        return jsonify(
            {
                "error": "Activity-pack generation failed.",
                "detail": str(exc),
            }
        ), 500


@app.get("/output/<path:filename>")
def download_output(filename: str) -> object:
    """Serve a generated PDF from the configured output directory/volume."""

    if not filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are available."}), 404
    return send_from_directory(Path(OUTPUT_DIR).resolve(), filename, as_attachment=True)


@app.errorhandler(413)
def request_too_large(_: Exception) -> tuple[object, int]:
    """Return JSON when a request exceeds the configured limit."""

    return jsonify({"error": "Request body is too large."}), 413


@app.get("/")
@app.get("/books")
def books_page():
    """Show the public book library with download links."""
    return render_template("books.html", books=list_books())


@app.get("/api/books")
def books_api():
    """Return all known books and file availability."""
    return jsonify(books=list_books())


@app.get("/internal/state")
def library_state():
    """Allow the cron service to read current rotation history."""
    if not delivery_authorized():
        return jsonify(error="Unauthorized"), 401
    return jsonify(load_state())


def delivery_authorized():
    """Require a configured shared secret for internal delivery endpoints."""
    expected = os.environ.get("DELIVERY_TOKEN", "")
    return bool(expected) and hmac.compare_digest(expected, request.headers.get("X-Delivery-Token", ""))


@app.post("/internal/books")
def upload_book():
    """Receive a cron PDF and metadata, with idempotent filename handling."""
    if not delivery_authorized():
        return jsonify(error="Unauthorized"), 401
    try:
        metadata = json.loads(request.form.get("metadata", "{}"))
        if not isinstance(metadata, dict) or "pdf" not in request.files:
            raise ValueError("A PDF and metadata object are required")
        filename = receive_pdf(request.files["pdf"], metadata)
        return jsonify(status="stored", filename=filename), 201
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
