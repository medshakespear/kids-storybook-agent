"""Exact printable puzzle artwork and answers built from the same validated data.

These are optional visual components, not page templates. AI still chooses the
activity, composition and surrounding illustrations. No model-generated code runs.
"""
from __future__ import annotations

import html
import random
import re
from functools import lru_cache
import json

COLORS = {'orange': '#ED8936', 'teal': '#219E9A', 'purple': '#9063B5',
          'yellow': '#F2C94C', 'red': '#DF5763', 'blue': '#508FCC', 'green': '#62A86E',
          'white': '#FFFFFF', 'black': '#252A34', 'pink': '#F09DB9', 'brown': '#A06A42',
          'gray': '#88939E'}
SHAPES = {'circle', 'square', 'triangle', 'star', 'leaf', 'pumpkin', 'ghost', 'bat'}
SIZES = {'small': 0.65, 'large': 1.0}


def integer(value, name: str, low: int, high: int) -> int:
    """Accept bounded JSON integers, excluding booleans."""
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer from {low} to {high}')
    return value


def symbol(raw: dict, context: str = 'Symbol') -> dict:
    """Validate a vector symbol without accepting arbitrary SVG or CSS."""
    if not isinstance(raw, dict):
        raise ValueError(f'{context}: each symbol must be an object with shape, color and size')
    shape = raw.get('shape')
    color = raw.get('color', raw.get('colour'))
    shape = shape.strip().lower() if isinstance(shape, str) else None
    color = color.strip().lower() if isinstance(color, str) else None
    plurals = {s+'s': s for s in SHAPES}
    plurals['leaves'] = 'leaf'
    shape = plurals.get(shape, shape)
    color = {'grey': 'gray', **{v.lower(): k for k,v in COLORS.items()}}.get(color, color)
    if shape not in SHAPES or color not in COLORS:
        raise ValueError(f'{context}: each symbol needs a supported shape and color; '
                         f'received shape={str(raw.get("shape"))[:60]!r}, color={str(raw.get("color", raw.get("colour")))[:60]!r}. '
                         f'Shapes: {", ".join(sorted(SHAPES))}. Colors: {", ".join(sorted(COLORS))}')
    size = raw.get('size', 'large')
    size = size.strip().lower() if isinstance(size, str) else None
    if size not in SIZES:
        raise ValueError(f'{context}: Symbol size must be small or large')
    return dict(shape=shape, color=color, size=size)


def icon(item: dict, x: float, y: float, scale: float = 1) -> str:
    """Draw one consistent vector symbol with a visible outline."""
    shape, color = item['shape'], COLORS[item['color']]
    if shape == 'circle':
        body = '<circle cx="0" cy="0" r="28"/>'
    elif shape == 'square':
        body = '<rect x="-26" y="-26" width="52" height="52" rx="5"/>'
    elif shape == 'triangle':
        body = '<path d="M 0,-30 L 30,27 L -30,27 Z"/>'
    elif shape == 'star':
        body = '<path d="M0,-30 L9,-10 L30,-9 L15,7 L20,29 L0,17 L-20,29 L-15,7 L-30,-9 L-9,-10 Z"/>'
    elif shape == 'leaf':
        body = '<path d="M-25,25 Q-40,-25 27,-28 Q42,26 -25,25 Z"/><path d="M-25,25 L20,-20" fill="none"/>'
    elif shape == 'ghost':
        eyes = '#233544' if item['color'] in {'white','yellow','pink'} else '#FFFFFF'
        body = ('<path d="M-24,30 V-8 A24,24 0 0 1 24,-8 V30 L12,22 L0,30 L-12,22 Z"/>'
                f'<g fill="{eyes}" stroke="none"><circle cx="-8" cy="-6" r="3"/>'
                '<circle cx="8" cy="-6" r="3"/><path d="M-5,7 Q0,12 5,7" fill="none" '
                f'stroke="{eyes}" stroke-width="2"/></g>')
    elif shape == 'bat':
        body = '<path d="M0,-8 L-7,-21 L-11,-7 L-36,-23 L-30,3 Q-20,-3 -16,15 Q-8,10 0,25 Q8,10 16,15 Q20,-3 30,3 L36,-23 L11,-7 L7,-21 Z"/>'
    else:
        body = ('<path d="M-4,-22 L-2,-36 L6,-36 L4,-22" fill="#468453"/>'
                '<ellipse cx="-13" cy="3" rx="19" ry="26"/><ellipse cx="13" cy="3" rx="19" ry="26"/>'
                '<ellipse cx="0" cy="3" rx="17" ry="28"/>')
    return (f'<g transform="translate({x:g},{y:g}) scale({scale * SIZES[item["size"]]:g})" '
            f'fill="{color}" stroke="#344454" stroke-width="2.5" stroke-linejoin="round">{body}</g>')


def text(x: float, y: float, value: str, size: int = 20, anchor: str = 'middle') -> str:
    """Escape labels and provide a font available in the deployment image."""
    return (f'<text x="{x:g}" y="{y:g}" font-family="DejaVu Sans" font-size="{size}" '
            f'text-anchor="{anchor}" fill="#233544" stroke="none">{html.escape(value)}</text>')


def maze_data(rows: int, cols: int, seed: int) -> tuple[set, list]:
    """Build a perfect maze and its unique start-to-finish solution with local RNG."""
    rng = random.Random(seed)
    start, finish = (0, 0), (rows - 1, cols - 1)
    visited, stack, passages, parents = {start}, [start], set(), {}
    while stack:
        r, c = stack[-1]
        neighbors = [(nr, nc) for nr, nc in [(r-1,c), (r+1,c), (r,c-1), (r,c+1)]
                     if 0 <= nr < rows and 0 <= nc < cols and (nr, nc) not in visited]
        if not neighbors:
            stack.pop()
            continue
        nxt = rng.choice(neighbors)
        passages.add(frozenset(((r, c), nxt)))
        parents[nxt] = (r, c)
        visited.add(nxt)
        stack.append(nxt)
    path = [finish]
    while path[-1] != start:
        path.append(parents[path[-1]])
    return passages, list(reversed(path))


def route_text(path: list) -> str:
    """Compress the verified route into printable direction/run instructions."""
    runs = []
    for (r, c), (nr, nc) in zip(path, path[1:]):
        direction = {(1,0):'D', (-1,0):'U', (0,1):'R', (0,-1):'L'}[(nr-r, nc-c)]
        if runs and runs[-1][0] == direction:
            runs[-1][1] += 1
        else:
            runs.append([direction, 1])
    return ' '.join(f'{d}{n}' for d, n in runs)


def build_visual(spec: dict) -> tuple[str, str]:
    """Validate a component and return its exact SVG and answer-key entry."""
    if not isinstance(spec, dict) or not re.fullmatch(r'[a-z][a-z0-9_]{0,30}', str(spec.get('id', ''))):
        raise ValueError('Visual needs a short lowercase id')
    q = integer(spec.get('question'), 'Visual question number', 1, 30)
    kind = spec.get('kind')
    parts, height = [], 430
    if kind == 'maze':
        rows = integer(spec.get('rows'), 'Maze rows', 4, 8)
        cols = integer(spec.get('cols'), 'Maze columns', 4, 8)
        seed = integer(spec.get('seed'), 'Maze seed', 0, 2147483647)
        tokens = integer(spec.get('tokens', 0), 'Maze tokens', 0, 5)
        passages, path = maze_data(rows, cols, seed)
        if tokens > len(path) - 2:
            raise ValueError('Too many maze tokens for the solution path')
        parts.append(text(360, 30, f'{q}. Trace from START to FINISH.', 24))
        parts.append(text(360, 63, 'Count the stars along your route.', 20))
        cell = min(610 / cols, 430 / rows)
        x0, y0 = (720 - cols * cell) / 2, 110
        height = int(y0 + rows * cell + 50)
        stars = {path[1 + (i + 1) * (len(path) - 2) // (tokens + 1)] for i in range(tokens)}
        for r in range(rows):
            for c in range(cols):
                x, y = x0 + c*cell, y0 + r*cell
                if r == 0:
                    parts.append(f'<path d="M{x},{y} h{cell}"/>')
                if c == 0 and r != 0:
                    parts.append(f'<path d="M{x},{y} v{cell}"/>')
                if r == rows-1 or frozenset(((r,c),(r+1,c))) not in passages:
                    parts.append(f'<path d="M{x},{y+cell} h{cell}"/>')
                if (c == cols-1 and r != rows-1) or (c < cols-1 and frozenset(((r,c),(r,c+1))) not in passages):
                    parts.append(f'<path d="M{x+cell},{y} v{cell}"/>')
                if (r,c) in stars:
                    parts.append(icon(dict(shape='star',color='yellow',size='large'),x+cell/2,y+cell/2,cell/115))
        parts.extend([text(x0+cell/2, y0-13, 'START', 18),
                      text(x0+(cols-.5)*cell, y0+rows*cell+30, 'FINISH', 18)])
        answer = f'{q}. {tokens} stars. Route from START (U/D/L/R): {route_text(path)}.'
    elif kind == 'differences':
        items = spec.get('items')
        if not isinstance(items, list) or not 4 <= len(items) <= 8:
            raise ValueError('Differences needs 4-8 symbols')
        first = [symbol(item, f'Visual {spec["id"]}, item {i}') for i,item in enumerate(items, 1)]
        second = [dict(i) for i in first]
        changes, changed = spec.get('changes'), set()
        if not isinstance(changes, list) or not 1 <= len(changes) <= len(items):
            raise ValueError('Provide 1-N differences')
        for change in changes:
            if not isinstance(change, dict):
                raise ValueError('A difference must be an object')
            index = integer(change.get('index'), 'Difference index (one-based)', 1, len(items)) - 1
            field = change.get('field')
            if index in changed or field not in {'shape','color','size'}:
                raise ValueError('Change one trait per distinct item')
            second[index][field] = change.get('value')
            second[index] = symbol(second[index], f'Visual {spec["id"]}, changed item {index+1}')
            if second[index] == first[index]:
                raise ValueError('Each difference must actually change a visible trait')
            changed.add(index)
        parts.extend([text(360,30,f'{q}. Compare rows A and B.',24),
                      text(360,65,f'Circle the {len(changed)} changed pictures in row B.',20)])
        cell = 630 / len(items)
        for row, symbols in enumerate((first, second)):
            y = 160 + row*165
            parts.append(text(25,y,'AB'[row],24))
            for i, item in enumerate(symbols):
                x = 68 + (i+.5)*cell
                parts.append(icon(item,x,y,min(1.4,cell/72)))
                parts.append(text(x,y+65,str(i+1),20))
        answer = f'{q}. Row B positions: ' + ', '.join(str(i+1) for i in sorted(changed)) + '.'
    elif kind == 'sort':
        items, attribute = spec.get('items'), spec.get('attribute')
        if not isinstance(items, list) or not 4 <= len(items) <= 8 or attribute not in {'shape','color','size'}:
            raise ValueError('Sort needs 4-8 symbols and attribute shape, color or size')
        symbols = [symbol(item, f'Visual {spec["id"]}, item {i}') for i,item in enumerate(items, 1)]
        values = list(dict.fromkeys(item[attribute] for item in symbols))
        if not 2 <= len(values) <= 3:
            raise ValueError('Sorting needs exactly 2-3 disjoint groups')
        parts.extend([text(360,30,f'{q}. Sort the pictures by {attribute}.',24),
                      text(360,65,'Write each picture number in the matching box.',20)])
        for i,item in enumerate(symbols):
            x,y = 100 + (i%4)*173, 145 + (i//4)*125
            parts.extend([icon(item,x,y,1.2), text(x,y+53,str(i+1),20)])
        bottom = 365 if len(items)>4 else 240
        width = 670 / len(values)
        for i,value in enumerate(values):
            x = 25 + i*width
            parts.append(f'<rect x="{x}" y="{bottom}" width="{width-12}" height="125" rx="14" fill="#F1F8FA"/>')
            parts.append(text(x+(width-12)/2,bottom+35,value.title(),22))
            parts.append(f'<path d="M{x+18},{bottom+92} h{width-48}" stroke="#657989" stroke-width="1"/>')
        height = bottom + 140
        answer = f'{q}. ' + '; '.join(v.title()+': '+', '.join(str(i+1) for i,item in enumerate(symbols) if item[attribute]==v) for v in values) + '.'
    else:
        raise ValueError('Visual kind must be maze, differences or sort')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="720" height="{height}" viewBox="0 0 720 {height}">'
           '<rect width="100%" height="100%" fill="white"/>'
           '<g stroke="#344454" stroke-width="3" fill="none">'+''.join(parts)+'</g></svg>')
    return svg, answer


@lru_cache(maxsize=128)
def cached_visual(serialized: str) -> tuple[str, str]:
    """Reuse deterministic vector markup across preflight and final rendering."""
    return build_visual(json.loads(serialized))


def normalize_visual_metadata(page: dict) -> None:
    """Normalize explicit IDs and numeric strings without inventing puzzle metadata."""
    specs = page.get('visuals', [])
    if not isinstance(specs, list):
        return  # The strict validator supplies the schema error.
    mapping, seen = {}, set()
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        original = spec.get('id')
        if isinstance(original, str):
            normalized = re.sub(r'[\s-]+', '_', original.strip().lower())
            if re.fullmatch(r'[a-z][a-z0-9_]{0,30}', normalized):
                if normalized in seen:
                    raise ValueError('Visual IDs collide after normalization; supply distinct lowercase ids')
                seen.add(normalized)
                mapping[original] = normalized
                spec['id'] = normalized
        question = spec.get('question')
        if isinstance(question, str) and re.fullmatch(r'\s*\d{1,2}\s*', question):
            spec['question'] = int(question.strip())
    def replace_reference(match):
        """Update the HTML reference to the exact same explicit visual ID."""
        original = html.unescape(match[2])
        return match[1] + mapping.get(original, match[2]) + match[3]
    page['html'] = re.sub(r'(\bdata-visual\s*=\s*[\'"])([^\'"]*)([\'"])',
                          replace_reference, page['html'], flags=re.I)


def page_visuals(page: dict) -> dict[str, tuple[str, str]]:
    """Validate visual IDs and numbers and compile every requested component."""
    specs = page.get('visuals', [])
    if not isinstance(specs, list) or len(specs) > 3:
        raise ValueError('visuals must be a list of at most three exact components')
    result, questions = {}, set()
    for spec in specs:
        svg, answer = cached_visual(json.dumps(spec, sort_keys=True))
        if spec['id'] in result or spec['question'] in questions:
            raise ValueError('Visual IDs and question numbers must be unique per page')
        result[spec['id']] = (svg, answer)
        questions.add(spec['question'])
    return result


def answer_text(page: dict) -> str:
    """Assemble the key with exact puzzle answers, never an AI guess about artwork."""
    return ' '.join([v[1] for v in page_visuals(page).values()] + [page.get('answers','')]).strip()


VISUAL_CONTRACT = '''Optional exact visuals: use <img data-visual="id" style="width:175mm;height:130mm"/>.
Declare each in visuals (0-3 objects); Python draws them sharply and adds their numbered answers.
Each object MUST have id matching [a-z][a-z0-9_]{0,30}, question as a JSON INTEGER 1-30
(not a string, page number, zero, null or object), kind, and the following fields.
The question number matches the numbered task and must be unique on this page. Example:
{"id":"trail","question":1,"kind":"maze","rows":5,"cols":5,"seed":12,"tokens":3}.
Use the SAME id in HTML data-visual="trail". images holds Cloudflare art; visuals holds these
exact puzzle objects. Never put illustration prompts in visuals or omit id/question.
- maze: rows/cols integers 4-8, seed integer 0-2147483647, tokens integer 0-5. Python draws a real
  solvable maze, START/FINISH and precisely that many stars on its route. Use height:145mm.
- differences: items list of 4-8 {shape,color,size}; changes list of {index:1-based,field,value}.
  Each index occurs once; change exactly one visible field. Python draws BOTH numbered rows.
- sort: attribute shape/color/size; items list of 4-8 {shape,color,size} with 2-3 distinct values
  for that attribute. Python derives exhaustive, disjoint bins and exact membership. Height:140mm.
Shapes: circle,square,triangle,star,leaf,pumpkin,ghost,bat.
Colors: orange,teal,purple,yellow,red,blue,green,white,black,pink,brown,gray.
Every item MUST explicitly contain shape and color from these lists, plus size: small or large.
Do not invent unsupported objects or palette names in exact visuals. Use images for other subjects.
Sizes: small,large. Use theme-appropriate shapes, and vary composition instead of repeating components.
These are optional drawing tools, NOT a required list of exercises. Other original activities are welcome.
For mazes, spot-the-difference and closed-rule picture sorting, ALWAYS use these exact visuals.
Never fake a maze or differences exercise with Cloudflare art, empty boxes, CSS drawings or descriptive labels.
Do not repeat the exact visual's question or answer in HTML/answers: Python prints its directions,
question number and answer. Your answers field covers ONLY other questions on the page.
'''
