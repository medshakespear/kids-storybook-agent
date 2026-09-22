"""Generate bounded, original classroom exercises, not narrative storybooks."""
from __future__ import annotations

import json
import logging
import random
import re
import time
from copy import deepcopy

from core.providers import text_client, text_provider_names, safe_api_error

ICONS = {"circle", "square", "triangle", "star", "heart", "leaf", "book"}


class ActivityGenerationError(RuntimeError):
    """All configured text providers failed to produce a valid activity pack."""


def _text(value: object, name: str, maximum: int) -> str:
    """Require bounded nonblank text so student material cannot overflow silently."""
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{name} must be nonempty text of at most {maximum} characters")
    return value.strip()


def _strings(value: object, name: str, low: int, high: int, length: int) -> list[str]:
    """Validate a bounded list of printable strings."""
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise ValueError(f"{name} must contain {low}-{high} entries")
    return [_text(item, name, length) for item in value]


def _integer(value: object, name: str, low: int, high: int) -> int:
    """Normalize unambiguous integer encodings without rounding or clamping values."""
    if isinstance(value, str) and re.fullmatch(r"-?\d{1,10}", value.strip()):
        value = int(value.strip())
    elif type(value) is float and value.is_integer():
        value = int(value)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}")
    return value


def validate_pack(raw: dict, theme: str, grade_band: str, config: dict, *, check_diversity: bool = True) -> dict:
    """Validate print bounds, allowed activities and deterministic math answer keys."""
    if not isinstance(raw, dict):
        raise ValueError("Pack must be a JSON object")
    pack = deepcopy(raw)
    for key, maximum in {"title": 80, "overview": 350}.items():
        pack[key] = _text(pack.get(key), key, maximum)
    pack["materials"] = _strings(pack.get("materials"), "materials", 1, 5, 65)
    pack["objectives"] = _strings(pack.get("objectives"), "objectives", 2, 4, 110)
    pages = pack.get("pages")
    if not isinstance(pages, list) or len(pages) != config["activity_pages"]:
        raise ValueError(f"Exactly {config['activity_pages']} student pages are required")
    seen_types, titles = set(), set()
    for number, page in enumerate(pages, 1):
        item_index = None
        try:
            if not isinstance(page, dict) or page.get("type") not in config["allowed_types"]:
                raise ValueError(f"Page {number} uses an unsupported activity type")
            kind = page["type"]
            seen_types.add(kind)
            for key, maximum in {"title": 55, "instructions": 140}.items():
                page[key] = _text(page.get(key), key, maximum)
            if page["title"].casefold() in titles:
                raise ValueError("Page titles must be unique")
            titles.add(page["title"].casefold())
            page["page_number"] = number
            items = page.get("items")
            if not isinstance(items, list):
                raise ValueError("Every page must have an items list")
            expected = 0 if kind == "draw" else config["items_per_page"]
            if len(items) != expected or not all(isinstance(item, dict) for item in items):
                raise ValueError(f"Page {number} needs exactly {expected} item objects")
            if kind == "sort":
                page["categories"] = _strings(page.get("categories"), "categories", 2, 2, 28)
                if len(set(page["categories"])) != 2:
                    raise ValueError("Sorting categories must be different")
            if kind == "reading":
                page["passage"] = _text(page.get("passage"), "passage", 750)
                if len(page["passage"].split()) < 40:
                    raise ValueError("Reading passage needs at least 40 words")
            if kind == "draw":
                page["challenge"] = _text(page.get("challenge"), "challenge", 250)
                page["criteria"] = _strings(page.get("criteria"), "criteria", 2, 3, 100)
                page["sample_response"] = _text(page.get("sample_response"), "sample_response", 180)
                page["answers"] = ["Open-ended. " + page["sample_response"]]
            else:
                page["answers"] = []
            for item_index, item in enumerate(items, 1):
                if kind == "picture_choice":
                    item["question"] = _text(item.get("question"), "question", 100)
                    item["choices"] = _strings(item.get("choices"), "choices", 3, 3, 65)
                    if len(set(item["choices"])) != 3:
                        raise ValueError("Choices must be distinct")
                    correct = _integer(item.get("correct"), "correct", 0, 2)
                    item['correct'] = correct
                    answer = chr(65 + correct)
                elif kind == "count":
                    count = _integer(item.get("count"), "count", 1, 10)
                    item['count'] = count
                    if item.get("icon") not in ICONS:
                        raise ValueError("Count icon must be one of " + ", ".join(sorted(ICONS)))
                    answer = str(count)
                elif kind == "arithmetic":
                    a = _integer(item.get("a"), "a", 0, config["max_operand"])
                    b = _integer(item.get("b"), "b", 0, config["max_operand"])
                    item.update(a=a, b=b)
                    op = item.get("op")
                    if op not in config["operations"]:
                        raise ValueError("Arithmetic operation is unsuitable for this band")
                    if op == "/" and (b == 0 or a % b):
                        raise ValueError("Division needs a nonzero divisor and an exact integer result")
                    result = {"+": lambda: a + b, "-": lambda: a - b,
                              "*": lambda: a * b, "/": lambda: a // b}[op]()
                    if not 0 <= result <= config["max_result"]:
                        raise ValueError("Arithmetic answer is outside the grade range")
                    answer = str(result)
                elif kind == "matching":
                    item["left"] = _text(item.get("left"), "left", 65)
                    item["right"] = _text(item.get("right"), "right", 65)
                    answer = f"{item['left']} -> {item['right']}"
                elif kind == "sort":
                    item["label"] = _text(item.get("label"), "label", 45)
                    category = _integer(item.get("category"), "category index", 0, 1)
                    item['category'] = category
                    answer = f"{item['label']} -> {page['categories'][category]}"
                elif kind == "reading":
                    item["question"] = _text(item.get("question"), "question", 120)
                    answer = _text(item.get("answer"), "answer", 100)
                elif kind == "trace":
                    word = _text(item.get("word"), "word", 10)
                    if not word.isascii() or not word.isalpha():
                        raise ValueError("Trace words must contain only ASCII letters")
                    item["word"] = word.upper()
                    answer = item["word"] + " (trace, then independently copy)"
                page["answers"].append(answer)
            if kind == "matching" and (len({i['left'] for i in items}) != len(items) or len({i['right'] for i in items}) != len(items)):
                raise ValueError("Matching entries must be unique for an unambiguous key")
            if kind == "sort" and {i['category'] for i in items} != {0, 1}:
                raise ValueError("Use both sorting categories")
        except (ValueError, TypeError, KeyError) as exc:
            location = f"Page {number}" + (f", item {item_index}" if item_index is not None else "")
            raise ValueError(f"{location}: {exc}") from None
    if check_diversity and len(seen_types) < 3:
        raise ValueError("A pack needs at least three different activity types")
    pack.update(theme=theme, grade_band=grade_band, resource_type="activity_pack")
    return pack


def validate_visuals(pack: dict) -> dict:
    """Require original illustration briefs for every visual task before API spending."""
    pack["character_description"] = _text(pack.get("character_description"), "character_description", 350)
    for number, page in enumerate(pack["pages"], 1):
        if page["type"] in {"reading", "arithmetic", "draw"}:
            page["image_prompt"] = _text(page.get("image_prompt"), f"Page {number}: image_prompt", 650)
        else:
            for index, item in enumerate(page["items"], 1):
                fields = ("left_image_prompt", "right_image_prompt") if page["type"] == "matching" else ("image_prompt",)
                for field in fields:
                    item[field] = _text(item.get(field), f"Page {number}, item {index}: {field}", 650)
    return pack


def _prompt(theme: str, grade_band: str, config: dict, source_context: str | None) -> str:
    """Describe the supported exercise contract and originality requirements."""
    return f"""Create an original print-and-go classroom ACTIVITY PACK, not a storybook.
Theme: {theme}. Grade band: {grade_band}. Skills: {config['skill_notes']}
Return one JSON object with title, overview, materials (1-5 strings), objectives (2-4 strings), pages.
Exactly {config['activity_pages']} student pages, each with exactly {config['items_per_page']} items
except draw pages which have items: []. Use at least three types from {config['allowed_types']}.
Every page: title (55 chars max), type, instructions (140 chars max), items.
Do not write a teacher guide, teaching tips, support, extensions or lesson plans.
Pack also needs character_description (<=350 chars): an original consistent cast and clothing.
At least two pages must be picture_choice. Pictures must carry useful task information.
picture_choice items: question <=100 chars, choices (three distinct strings <=65 chars),
correct (zero-based index 0-2), image_prompt (<=650 chars, clearly depicts the scenario).
Vary the correct answer position. Young grades: very short adult-read choices.
ALL count/sort/trace items need image_prompt <=650 chars: one recognizable isolated object on white.
Count: depict ONE object only, never a group; code repeats that image the exact count.
Trace: depict precisely the concrete word. Sort: depict precisely the labeled object.
ALL matching items need left_image_prompt AND right_image_prompt, <=650 chars each.
Use visually unambiguous relationships (object/use, animal/home), not abstract text definitions.
Reading/arithmetic/draw pages need page.image_prompt <=650 chars: a meaningful supporting scene.
No image may contain text, numbers, labels, answer marks, a worksheet, or multiple panels.
Frame the entire subject in the center with generous margins; illustration is fitted without cropping.
Use only these item structures for their corresponding type:
count: {{"count": 5, "icon": "leaf"}} plus image_prompt. Icons: {sorted(ICONS)}. Counts 1-10. Code repeats the generated object image.
arithmetic: {{"a": 8, "op": "+", "b": 3}}. Operands 0-{config['max_operand']},
nonnegative answers at most {config['max_result']}, operations {config['operations']}.
Division must be exact. Code calculates answers; directions must NOT reference unseen word problems.
matching: {{"left": "word or idea", "right": "matching meaning or connection"}}. Both <=65 chars, all unique.
sort: {{"label": "thing to sort", "category": 0}} plus page.categories: ["Category A", "Category B"].
Use both categories (indexes 0 and 1). Items are illustrated cut-out cards with short labels.
reading: {{"question": "Question based on the passage", "answer": "Complete answer"}} plus
page.passage: a complete original informational passage, 40-110 words and <=750 chars.
Aim for 55-85 words to stay safely above the minimum; count words before returning.
Arithmetic a and b must be JSON integers, not quoted words, fractions or expressions.
Check EACH operand independently against its limit, not just the final answer.
Questions <=120 chars, answers <=100 chars. Do not require external materials or links.
trace: {{"word": "leaf"}}. ASCII letters only, 1-10 characters, familiar short words. These are
outlined uppercase tracing words, not student names. Never promise editable/personalized resources.
draw: page.challenge <=250 chars, page.criteria 2-3 strings <=100 chars each,
page.sample_response <=180 chars, items: []. Give a concrete creative task and meaningful criteria.
Overview <=350 chars, title <=80 chars, each objective <=110 chars, each material <=65 chars.
Make tasks meaningfully different, scaffolded and relevant to the theme. Balance skill practice
with creative thinking. Design older-grade tasks to require reasoning, not preschool exercises.
All needed task content must be included. Do not say 'insert picture', 'use a text', or add placeholders.
The renderer provides AI pictures, answer boxes, matching columns, cut cards, tracing and drawing areas.
Use the supplied illustrations in the task. Quantities, precise diagrams and math must not depend
on image-model accuracy; code draws counted objects and equations. Do not request invented charts.
Use respectful, inclusive, accurate content; no stereotypes, invented historical claims, quotations,
copyrighted characters, brands, hazardous activities, or promises of standards alignment.
Adults read directions and text cards aloud for Pre-K-K. Never require personal information.
{source_context or 'Invent fresh content, not a copy or paraphrase of an existing commercial product.'}
Return JSON only, without markdown. Answer keys must actually answer every task."""


def invalid_pages(raw: dict, theme: str, band: str, config: dict) -> dict[int, str]:
    """Locate independently repairable pages; leave global structural errors to full retry."""
    if not isinstance(raw, dict) or not isinstance(raw.get('pages'), list) or len(raw['pages']) != config['activity_pages']:
        return {}
    failures = {}
    for index, page in enumerate(raw['pages'], 1):
        single = dict(raw, pages=[page])
        try:
            validate_visuals(validate_pack(single, theme, band, dict(config, activity_pages=1), check_diversity=False))
        except (ValueError, TypeError, KeyError) as exc:
            failures[index] = str(exc).replace('Page 1:', f'Page {index}:').replace('Page 1,', f'Page {index},')
    return failures


def merge_repairs(draft: dict, response: dict, requested: dict[int, str]) -> dict:
    """Apply exactly the requested replacement pages, never drop valid existing work."""
    pages = response.get('pages') if isinstance(response, dict) else None
    if not isinstance(pages, list):
        raise ValueError('Repair response needs a pages list')
    replacements = {}
    for page in pages:
        number = page.get('page_number') if isinstance(page, dict) else None
        if type(number) is not int or number not in requested or number in replacements:
            raise ValueError('Repair returned duplicate or unexpected page numbers')
        replacements[number] = page
    if set(replacements) != set(requested):
        raise ValueError('Repair did not return every requested page')
    result = deepcopy(draft)
    for number, page in replacements.items():
        result['pages'][number - 1] = page
    return result


def generate_activity_pack(theme: str, grade_band: str, grade_config: dict, *,
                           source_context: str | None = None, max_retries: int = 4) -> dict:
    """Generate a validated pack, retrying constraints and using configured fallback."""
    if grade_band not in grade_config or max_retries < 1:
        raise ValueError("Invalid grade band or retry count")
    config = grade_config[grade_band]
    prompt = _prompt(theme, grade_band, config, source_context)
    errors = []
    draft, repairs, feedback = None, {}, ''
    for provider in text_provider_names():
        api, model = text_client(provider)
        try:
            for attempt in range(max_retries):
                try:
                    logging.getLogger(__name__).info("Activity pack: %s / %s, attempt %s", provider, model, attempt + 1)
                    request = prompt + feedback
                    if repairs:
                        request = prompt + '\nREPAIR MODE: Return only {"pages": [...]} with complete replacement pages for these page numbers. Include page_number in each. Keep the task type. Repair the passage AND its questions/answers together when needed. Do not return other pages or pack metadata.\n' + json.dumps({
                            'failures': repairs, 'pages': [dict(draft['pages'][n-1], page_number=n) for n in repairs],
                            'character_description': draft.get('character_description', '')})
                    response = api.chat.completions.create(model=model,
                        messages=[{"role": "system", "content": "You are a careful elementary curriculum writer. Return complete JSON exercises."},
                                  {"role": "user", "content": request}],
                        response_format={"type": "json_object"}, temperature=0.5,
                        max_completion_tokens=min(10000, 2000 * len(repairs)) if repairs else 10000)
                    content = response.choices[0].message.content
                    if not content:
                        raise ValueError("Empty response")
                    parsed = json.loads(content)
                    draft = merge_repairs(draft, parsed, repairs) if repairs else parsed
                    pack = validate_visuals(validate_pack(draft, theme, grade_band, config))
                    if sum(p['type'] == 'picture_choice' for p in pack['pages']) < 2:
                        raise ValueError("Include at least two picture_choice pages")
                    return pack
                except (ValueError, TypeError, KeyError, IndexError) as exc:
                    error = f"{provider}: invalid activity content ({exc})"
                    feedback = f"\nCorrect this validation failure and regenerate the complete JSON: {exc}"
                    repairs = invalid_pages(draft, theme, grade_band, config)
                    logging.getLogger(__name__).warning('%s; next action: %s', error,
                        'repair pages ' + ', '.join(map(str, repairs)) if repairs else 'regenerate invalid pack structure')
                    errors.append(error)
                except Exception as exc:
                    failure = safe_api_error(provider, exc, model=model)
                    error = str(failure)
                    errors.append(error)
                    logging.getLogger(__name__).warning('%s', error)
                    # A quota response is not helped by four immediate repeat requests.
                    if getattr(exc, 'status_code', None) == 429:
                        break
                    if not failure.retryable:
                        break
                if attempt < max_retries - 1:
                    time.sleep(min(2 ** attempt + random.random(), 20))
        finally:
            api.close()
    raise ActivityGenerationError("Activity generation failed. " + "; ".join(dict.fromkeys(errors))) from None
