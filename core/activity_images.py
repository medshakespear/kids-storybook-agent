"""Generate and attach task-specific illustrations using the configured image API."""
from pathlib import Path

from core.activity_generator import validate_visuals
from core.image_generator import generate_images


def generate_activity_images(pack: dict, config: dict, folder: str | Path) -> None:
    """Deduplicate identical briefs within a pack and attach local image paths in place."""
    validate_visuals(pack)
    requests, bindings, seen = [], [], {}
    for page in pack['pages']:
        targets = [(page, 'image_prompt', 'art')] if page['type'] in {'reading', 'arithmetic', 'draw'} else []
        for item in page['items']:
            if page['type'] == 'matching':
                targets.extend([(item, 'left_image_prompt', 'left_art'), (item, 'right_image_prompt', 'right_art')])
            elif page['type'] in {'count', 'sort', 'trace', 'picture_choice'}:
                targets.append((item, 'image_prompt', 'art'))
        for target, field, output in targets:
            prompt = target[field]
            if prompt not in seen:
                seen[prompt] = len(requests)
                requests.append({'page_number': len(requests) + 1, 'image_prompt': prompt})
            bindings.append((target, output, seen[prompt]))
    art_pack = {'character_description': pack['character_description'], 'pages': requests,
                'resource_type': 'activity_pack'}
    paths = generate_images(art_pack, config, folder)
    if len(paths) != len(requests):
        raise ValueError('Illustration provider returned an incomplete set')
    for target, field, index in bindings:
        target[field] = str(paths[index])


def strip_local_art(pack: dict) -> None:
    """Remove temporary paths after PDF embedding so returned metadata stays portable."""
    for page in pack['pages']:
        for target in [page, *page['items']]:
            for key in ('art', 'left_art', 'right_art'):
                target.pop(key, None)
