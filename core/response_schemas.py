"""Small Gemini response schemas for each generation and repair stage.

Use the documented Gemini JSON Schema subset. String length limits live in
field descriptions and are enforced again by the shared Python validators.
"""
from copy import deepcopy

from core.task_visuals import COLORS, SHAPES


def text(limit: int, description: str = '') -> dict:
    """Describe nonempty bounded text without unsupported string schema keywords."""
    return {'type': 'string', 'description': f'Nonempty text, at most {limit} characters. {description}'.strip()}


def obj(properties: dict, required: list[str] | None = None) -> dict:
    """Build a closed object, allowing explicitly optional listed properties."""
    return {'type': 'object', 'properties': properties,
            'required': list(properties) if required is None else required,
            'additionalProperties': False}


def array(items: dict, low: int = 0, high: int = 4) -> dict:
    """Build a bounded, always-present JSON list rather than a nullable manifest."""
    return {'type': 'array', 'items': items, 'minItems': low, 'maxItems': high}


def enum(values) -> dict:
    """Constrain string labels to their literal supported values."""
    return {'type': 'string', 'enum': list(values)}


def integer(low: int, high: int) -> dict:
    """Reject strings, floats and nulls in exact puzzle integer fields."""
    return {'type': 'integer', 'minimum': low, 'maximum': high}


def manifest_schema(low: int = 1) -> dict:
    """Require explicit asset IDs and meaningful prompts for each illustration."""
    return array(obj({'id': text(31, 'Lowercase identifier, letters/digits/underscores; start with a letter.'),
                      'prompt': text(650, 'Original purposeful art; no text, numbers, borders or worksheet.') }), low, 4)


def visual_schema(kind: str) -> dict:
    """Expose only fields belonging to this planned exact mechanic."""
    symbol = obj({'shape': enum(sorted(SHAPES)), 'color': enum(sorted(COLORS)),
                  'size': enum(['small', 'large'])})
    fields = {'id': text(31, 'Short lowercase identifier matching data-visual.'),
              'question': integer(1, 30), 'kind': enum([kind])}
    specifications = {
        'maze': {'rows': integer(4, 8), 'cols': integer(4, 8), 'seed': integer(0, 2147483647), 'tokens': integer(0, 5)},
        'count': {'rows': array(array(symbol, 1, 10), 1, 3)},
        'balance': {'rows': array(obj({'left': symbol, 'right': symbol}), 1, 3)},
        'pattern': {'motif': array(symbol, 2, 3), 'choices': array(symbol, 2, 4)},
        'matching': {'mode': enum(['shadow', 'identical']), 'seed': integer(0, 2147483647), 'items': array(symbol, 2, 4)},
        'sort': {'attribute': enum(['shape', 'color', 'size']), 'items': array(symbol, 4, 8)},
        'differences': {'items': array(symbol, 4, 8), 'changes': array(obj({
            'index': integer(1, 8), 'field': enum(['shape', 'color', 'size']),
            'value': enum(sorted(SHAPES | set(COLORS) | {'small', 'large'}))}), 1, 8)},
    }
    fields.update(deepcopy(specifications[kind]))
    return obj(fields)


def question_schema(prompt_limit: int = 220, answer_limit: int = 180) -> dict:
    """Keep each printed question, workspace and verified result in one object."""
    return obj({'id': text(3, 'Distinct printed label, e.g. 1 or 2A.'),
                'prompt': text(prompt_limit, 'Aim for 140-220 characters. All numeric facts, units and rounding must fit; no decorative introduction.'),
                'answer': text(answer_limit, 'Aim for <=180 characters; retain every required solution or criterion.'),
                'space_mm': {'type': 'number', 'minimum': 0, 'maximum': 80},
                'calculation': obj({'expression': text(120, 'Numeric literals, parentheses and + - * / only. Include calculation only when the printed question asks for a numeric result; omit it for qualitative choices or explanations. Never copy the operation from another question.'),
                                    'answer': text(80, 'Exact number/fraction, or rounded result only if the question requests rounding.')})},
               ['id', 'prompt', 'answer', 'space_mm'])


def exercise_schema(brief: dict, config: dict) -> dict:
    """Lock the planned mechanism while permitting original task content."""
    from core.prompt_recovery import prompt_character_limit
    from core.answer_limits import answer_character_limit
    exact = brief['render_mode'] == 'exact'
    properties = {'render_mode': enum([brief['render_mode']]), 'mechanic': enum([brief['mechanic']]),
                  'goal': text(240),
                  'captions': array(obj({'id': text(24, 'Unique short lowercase identifier.'), 'text': text(120, 'Factual context label only; never task directions. Up to six context labels plus eight short diagram identifiers (e.g. Belt A). Do not use IDs directions/instructions/passage on exact pages.')}), 0, 14),
                  'questions': array(question_schema(prompt_character_limit(config), answer_character_limit(config)), 0 if exact else 1, config.get('items_per_page', 4))}
    if exact:
        properties['visual'] = visual_schema(brief['mechanic'])
        # One computed puzzle owns label 1. Additional actions use separate
        # labels, preventing collisions in the first response rather than
        # relying on a full-content repair to resolve them afterwards.
        properties['visual']['properties']['question'] = integer(1, 1)
        additional = properties['questions']
        additional['items']['properties']['id'] = enum(str(i) for i in range(2, 31))
        additional['maxItems'] = max(0, config.get('items_per_page', 4) - 1)
        additional['description'] = ('Additional original actions only, labelled 2 or higher. '
            'The computed visual is question 1 and counts toward the page action limit. '
            'Do not repeat its question or answer. Keep response space for every extra action.')
    else:
        properties['directions'] = text(180 if config.get('student_font_pt', 13) >= 14 else 350,
                                      'One concise task instruction, not a repeated question.')
        properties['passage'] = text(1500, 'Optional factual reading, keep short enough for the page.')
    required = [k for k in properties if k not in {'captions', 'passage'}]
    return obj(properties, required)


def design_schema(brief: dict | None = None, config: dict | None = None, *, cover: bool = False) -> dict:
    """Require page structure before requesting a completion, not only afterwards."""
    properties = {'html': text(18000, 'Balanced printable HTML with only supported inline styles. Empty data-content slots; each asset exactly once.'),
                  'images': manifest_schema(0 if brief and brief['render_mode'] == 'exact' else 1)}
    if not cover:
        properties['exercise'] = exercise_schema(brief, config or {})
    return obj(properties)


def mechanic_constraints_schema(mechanic: str) -> dict:
    """Allow only the selected tool's options, retaining rules implied by aliases."""
    from core.page_contract import canonical_mechanic
    kind, implied = canonical_mechanic(mechanic)
    properties = {}
    if kind == 'matching':
        properties['mode'] = enum([implied['mode']] if 'mode' in implied else ['shadow','identical'])
    elif kind == 'sort':
        properties['attribute'] = enum([implied['attribute']] if 'attribute' in implied else ['shape','color','size'])
    return obj(properties, list(implied))


def plan_schema(count: int) -> dict:
    """Bind optional matching/sorting options to their actual planned tool."""
    common = {'title':text(80), 'learning_goal':text(650), 'activity_concept':text(650),
              'layout_brief':text(650)}
    branches = []
    authored = {**common, 'render_mode':enum(['authored']),
                'mechanic':text(50,'Original creative action label.')}
    branches.append(obj(authored))
    for kinds in [['matching'], ['sort'], ['maze','count','balance','pattern','differences']]:
        fields = {**common, 'render_mode':enum(['exact']), 'mechanic':enum(kinds)}
        required = list(fields)
        if len(kinds) == 1:
            fields['mechanic_constraints'] = mechanic_constraints_schema(kinds[0])
        branches.append(obj(fields,required))
    return obj({**{k: text(n) for k, n in {'title': 80, 'overview': 350, 'art_direction': 650,
                                         'character_description': 350, 'cover_brief': 800}.items()},
                'pages': array({'anyOf':branches},count,count)})


def field_repair_schema(question_id: str, field: str, *, calculation: bool = False, answer_limit: int = 180) -> dict:
    """Make a one-question repair incapable of omitting its ID or changing other fields."""
    properties = {'id': enum([question_id]), field: text(220 if field == 'prompt' else answer_limit)}
    if calculation:
        properties['calculation'] = question_schema()['properties']['calculation']
    return obj({'exercise': obj({'questions': array(obj(properties), 1, 1)})})


def prompt_repair_messages(system: dict, original: dict, question_id: str, error: str) -> list[dict]:
    """Ask only for the failing prompt, including frozen facts instead of a whole design."""
    from core.prompt_recovery import numeric_tokens
    question = next(q for q in original['exercise']['questions'] if str(q.get('id')) == question_id)
    payload = {'id': question_id, 'original_prompt': question.get('prompt'),
               'numeric_tokens_to_preserve': numeric_tokens(question.get('prompt', '')),
               'retained_answer': question.get('answer'), 'retained_calculation': question.get('calculation')}
    import json
    return [system, {'role': 'user', 'content':
        'Shorten ONLY this question prompt to 1-220 characters (aim for 160). Preserve the complete '
        'student action, every numeric value and its unit, all conditions and explicit rounding. '
        'Remove decorative setup, not mathematical data. Never insert an answer. Return ONLY '
        '{"exercise":{"questions":[{"id":"'+question_id+'","prompt":"..."}]}}. '
        'Do not regenerate HTML, images or other exercise fields. If the previous correction lost a '
        'number, restore it from ORIGINAL_PROMPT below. Validation: '+error+'\n'+json.dumps(payload)}]


def audit_schema(count: int) -> dict:
    """Require a bounded content-review result for every student page."""
    return obj({'pages': array(obj({'page_number': integer(1,count),
                                   'issues': array(text(260,'Concrete content error only, not a stylistic preference.'),0,4)}),count,count)})
