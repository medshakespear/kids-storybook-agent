"""Local image-file validation only; no AI review or semantic regeneration."""
from pathlib import Path

from PIL import Image


class ImageFileError(RuntimeError):
    """An illustration is missing, corrupt, or too small to embed."""


def validate_image_files(paths: list[Path], expected: int) -> dict:
    """Decode each unique file locally without judging its visual content."""
    if len(paths) != expected:
        raise ImageFileError('Incomplete illustration set')
    seen = set()
    for number, value in enumerate(paths, start=1):
        try:
            path = Path(value)
            if path.resolve() in seen:
                raise ValueError('Duplicate image path')
            seen.add(path.resolve())
            with Image.open(path) as image:
                image.load()
                if min(image.size) < 256:
                    raise ValueError('Image is too small')
        except (OSError, ValueError, TypeError, Image.DecompressionBombError):
            raise ImageFileError(
                f'Image {number}: missing, duplicate, corrupt or undersized image file'
            ) from None
    return {'status': 'passed', 'checked': len(paths), 'method': 'local_file_decode'}
