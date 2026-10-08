"""Generate grade-appropriate reading passages and evidence-backed multiple-choice questions."""
from copy import deepcopy
import html
import re
import json
import random
import unicodedata

from core.creative_generator import ask_json
from core.creative_layout import check_page, preflight_pack
from core.grade_policy import require_active_grade
from core.providers import text_worker_limit
from core.response_schemas import array, enum, obj, text
from core.runtime import int_setting, ordered_parallel
from core.reading_answer_review import verify_question_answers

SKILLS = ('main_idea', 'detail', 'inference', 'vocabulary', 'cause_effect', 'text_structure', 'author_purpose', 'comparison')
LETTERS = ('A', 'B', 'C', 'D')


def bounded(value, name, limit):
    """Require nonempty plain text within the bounded print contract."""
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f'{name} must be nonempty text of at most {limit} characters')
    return value.strip()


def normalize_excerpt(value):
    """Compare copied excerpts across harmless typography and whitespace differences."""
    value = unicodedata.normalize('NFKC',value)
    value = value.translate(str.maketrans({'‘':"'",'’':"'",'“':'"','”':'"','–':'-','—':'-'}))
    return ' '.join(value.casefold().split())


def excerpt_in_passage(excerpt, paragraphs):
    """Require an existing contiguous excerpt; never use fuzzy semantic matching."""
    if not isinstance(excerpt,str) or not excerpt.strip():
        return False
    quote = excerpt.strip().strip('"“”')
    quote = normalize_excerpt(quote)
    if not quote:
        return False
    # A copied word/number must not be a fragment of a longer source token.
    start = r'(?<!\w)' if quote[0].isalnum() or quote[0]=='_' else ''
    end = r'(?!\w)' if quote[-1].isalnum() or quote[-1]=='_' else ''
    return re.search(start+re.escape(quote)+end,normalize_excerpt(' '.join(paragraphs))) is not None


def repair_unit_evidence(raw, label):
    """Repair only unsupported question/evidence pairs while freezing the passage."""
    if not isinstance(raw,dict) or not isinstance(raw.get('paragraphs'),list) or not 3 <= len(raw['paragraphs']) <= 4 or not all(isinstance(p,str) and p.strip() for p in raw['paragraphs']):
        return raw
    questions = raw.get('questions')
    if not isinstance(questions,list) or len(questions) != 5 or not all(isinstance(q,dict) for q in questions):
        return raw
    failed = {str(i):q for i,q in enumerate(questions,1) if isinstance(q,dict)
              and (not excerpt_in_passage(q.get('evidence'),raw['paragraphs'])
                   or len(str(q.get('evidence','')).strip()) > 180)}
    if not failed:
        return deepcopy(raw)
    unit = deepcopy(raw)
    def validate_evidence(repair):
        """Accept precisely the requested questions with actually copied excerpts."""
        replacements = repair.get('questions') if isinstance(repair,dict) else None
        if not isinstance(replacements,dict) or set(replacements) != set(failed):
            raise ValueError('Return only the requested question numbers')
        candidate = deepcopy(unit)
        for ref,question in replacements.items():
            if not isinstance(question,dict):
                raise ValueError('Each replacement question must be a JSON object')
            evidence = bounded(question.get('evidence'),f'Question {ref} evidence',180)
            if not excerpt_in_passage(evidence,unit['paragraphs']):
                raise ValueError(f'Question {ref}: copy a contiguous excerpt that actually occurs in the retained passage; do not paraphrase')
            candidate['questions'][int(ref)-1] = deepcopy(question)
        return candidate
    question_schema = unit_schema()['properties']['questions']['items']
    prompt = ('Repair ONLY these reading questions: '+', '.join(failed)+'. Their evidence is missing, '
              'paraphrased, too long or not present in the passage. Keep the passage, title, image prompt and '
              'all other questions unchanged. Independently solve each affected question from the retained passage. '
              'Copy a contiguous supporting excerpt of at most 180 characters DIRECTLY from a paragraph, '
              'including its exact words; no ellipsis or invented wording. Use a meaningful clause or sentence, '
              'not an isolated common word. Evidence must support the selected '
              'choice, not merely appear somewhere in the passage. Preserve the question and choices when '
              'supported. If no choice is defensibly correct, repair that affected question/choices instead '
              'of inserting new claims into the passage or selecting an unrelated quote. Keep one correct '
              'answer, skill mix and character limits. Return {"questions":{"number":{complete question}}} '
              'for precisely the listed numbers. Independent comprehension review follows.\n'+json.dumps(unit))
    return ask_json(prompt,validate_evidence,label+' evidence repair',3000,
                    response_schema=obj({'questions':obj({ref:question_schema for ref in failed})}))


def passage_word_count(paragraphs):
    """Count passage words identically in generation feedback and validation."""
    return len(re.findall(r"\b[\w]+(?:['’-][\w]+)*\b", ' '.join(paragraphs)))


def passage_length_feedback(paragraphs, config):
    """Give a measured expansion or reduction target inside the grade range."""
    count = passage_word_count(paragraphs)
    low, high = config['reading_words']['min'], config['reading_words']['max']
    target = (low + high) // 2
    action = f'add about {target-count} words' if count < target else f'remove about {count-target} words'
    return (f'Reading passage needs {low}-{high} words; received {count}. '
            f'Target {target} words: {action}. Use four balanced paragraphs of about {target//4} words. '
            'Count passage words only; questions and choices do not count. Preserve supporting quotations.')


def repair_unit_limits(raw, config, label):
    """Repair only passage length and overlong choices, retaining the rest of a draft."""
    if not isinstance(raw, dict):
        return raw
    unit = deepcopy(raw)
    paragraphs = unit.get('paragraphs')
    if isinstance(paragraphs,list) and 3 <= len(paragraphs) <= 4 and all(isinstance(p,str) and p.strip() for p in paragraphs):
        low, high = config['reading_words']['min'],config['reading_words']['max']
        if not low <= passage_word_count(paragraphs) <= high or any(len(p.strip()) > 1300 for p in paragraphs):
            source_questions = unit.get('questions')
            source_questions = source_questions if isinstance(source_questions,list) else []
            quotes = [q['evidence'] for q in source_questions if isinstance(q,dict)
                      and isinstance(q.get('evidence'),str) and q['evidence'].strip()
                      and excerpt_in_passage(q['evidence'],paragraphs)]
            def validate_passage(raw_repair):
                """Require the repaired length and every retained evidence quotation."""
                if not isinstance(raw_repair,dict) or not isinstance(raw_repair.get('paragraphs'),list):
                    raise ValueError('Return only an object containing paragraphs')
                result = raw_repair['paragraphs']
                if not 3 <= len(result) <= 4:
                    raise ValueError('Supply 3-4 balanced paragraphs')
                result = [bounded(p,'Paragraph',1300) for p in result]
                if not low <= passage_word_count(result) <= high:
                    raise ValueError(passage_length_feedback(result,config))
                if any(not excerpt_in_passage(q,result) for q in quotes):
                    raise ValueError('Passage length repair must retain every supporting quotation verbatim')
                return result
            prompt = ('Repair ONLY the passage length in this retained reading unit. Balance 3-4 paragraphs, each at most 1300 characters. '
                      +passage_length_feedback(paragraphs,config)+' '+config['reading_guidance']+
                      ' Expand with relevant explanations and concrete examples, never filler, invented statistics '
                      'or unverified cultural claims. Preserve facts and topic. Keep these EXISTING evidence quotations '
                      f'verbatim: {json.dumps(quotes)}. Never invent facts to justify an unsupported answer. '
                      'Do not change questions, answers, title or image prompt. Return {"paragraphs":[...]}.\n'
                      +json.dumps(unit))
            unit['paragraphs'] = ask_json(prompt,validate_passage,label+' passage-length repair',3000,
                                         response_schema=obj({'paragraphs':array(text(1300),3,4)}))
    questions = unit.get('questions')
    if not isinstance(questions,list):
        return unit
    overlong = {}
    for index,question in enumerate(questions,1):
        if isinstance(question,dict) and isinstance(question.get('options'),dict):
            for letter in LETTERS:
                value = question['options'].get(letter)
                if isinstance(value,str) and len(value.strip()) > 55:
                    overlong[f'{index}:{letter}'] = value
    if overlong:
        def validate_choices(raw_repair):
            """Require precisely the requested replacement choices without truncation."""
            replacements = raw_repair.get('replacements') if isinstance(raw_repair,dict) else None
            if not isinstance(replacements,dict) or set(replacements) != set(overlong):
                raise ValueError('Return exactly the requested replacement choice IDs')
            replacements = {ref:bounded(value,f'Choice {ref}',55) for ref,value in replacements.items()}
            candidate = deepcopy(unit)
            for ref,value in replacements.items():
                number,letter = ref.split(':')
                candidate['questions'][int(number)-1]['options'][letter] = value
            for question in candidate['questions']:
                if isinstance(question,dict) and isinstance(question.get('options'),dict):
                    values = [' '.join(str(v).casefold().split()) for v in question['options'].values()]
                    if len(set(values)) != len(values):
                        raise ValueError('Shortened choices must remain distinct')
            return candidate
        lengths = {ref:len(value.strip()) for ref,value in overlong.items()}
        prompt = ('Rewrite ONLY these overlong multiple-choice options as concise complete choices. '
                  f'Current character counts: {json.dumps(lengths)}. Each replacement must be 1-55 characters; '
                  'aim for 35-45 characters. Preserve meaning, negations, quantities, answer-letter correctness '
                  'and plausible distractors. Never truncate a sentence or swap letters. Keep all other fields '
                  'and choices unchanged. Return {"replacements":{"question:letter":"short choice"}} '
                  'with exactly the listed IDs. The independent comprehension review follows this repair.\n'
                  +json.dumps(unit))
        unit = ask_json(prompt,validate_choices,label+' choice-length repair',2000,
                        response_schema=obj({'replacements':obj({ref:text(55) for ref in overlong})}))
    return unit


def repair_unit_text(raw, label, *, retained=None):
    """Repair bounded wording fields without changing passages, choices or answers."""
    if not isinstance(raw,dict):
        return raw
    unit = deepcopy(raw)
    # Reading identity was already accepted; a review cannot silently rename it.
    if retained is not None:
        for key in ('title','image_prompt'):
            unit[key] = retained[key]
    questions = unit.get('questions')
    if not isinstance(questions,list) or len(questions)!=5 or not all(isinstance(q,dict) for q in questions):
        return unit
    targets = {}
    for key,limit in (('title',80),('image_prompt',650)):
        value = unit.get(key)
        if not isinstance(value,str) or not value.strip() or len(value.strip()) > limit:
            targets[key] = limit
    questions = unit.get('questions')
    if isinstance(questions,list) and len(questions)==5 and all(isinstance(q,dict) for q in questions):
        for number,question in enumerate(questions,1):
            for field,limit in (('prompt',120),('explanation',110)):
                value = question.get(field)
                if not isinstance(value,str) or not value.strip() or len(value.strip()) > limit:
                    targets[f'{number}:{field}'] = limit
    if not targets:
        return unit
    def validate_text(repair):
        """Accept only the requested field edits with complete, distinct question stems."""
        replacements = repair.get('replacements') if isinstance(repair,dict) else None
        if not isinstance(replacements,dict) or set(replacements) != set(targets):
            raise ValueError('Return precisely the requested wording field IDs')
        candidate = deepcopy(unit)
        for ref,limit in targets.items():
            value = bounded(replacements[ref],ref,limit)
            if ':' in ref:
                number,field = ref.split(':')
                candidate['questions'][int(number)-1][field] = value
            else:
                candidate[ref] = value
        stems = [normalize_excerpt(q['prompt']) for q in candidate.get('questions',[])
                 if isinstance(q,dict) and isinstance(q.get('prompt'),str)]
        if len(set(stems)) != len(stems):
            raise ValueError('Rewritten question prompts must remain distinct')
        return candidate
    prompt = ('Repair ONLY these bounded reading wording fields. Maximum character counts: '
              +json.dumps(targets)+'. Return complete concise wording, aiming below each limit. '
              'For explanations aim for 60-90 characters: one sentence explaining why the declared answer '
              'is supported by its passage evidence, not a new answer or lengthy teaching guide. '
              'For question prompts preserve all quantities, negations, requested reasoning and the correct '
              'choice; do not simplify the intellectual skill. For title/image prompt retain the same topic '
              'and visual intent. For missing wording infer it from the retained passage, choices and answer. '
              'Never truncate text, change the passage, options, answer letters, skills or evidence. '
              'Return {"replacements":{"field_id":"complete wording"}} with precisely the listed IDs.\n'
              +json.dumps(unit))
    return ask_json(prompt,validate_text,label+' wording repair',2500,
                    response_schema=obj({'replacements':obj({ref:text(limit) for ref,limit in targets.items()})}))



def passage_quality_issues(unit, config):
    """Flag extreme sentence density and unsupported appeals to research authority.

    Sentence length is a repair signal, not a certified reading-level score.
    Factual correctness and vocabulary still require the separate text review.
    """
    paragraphs = unit.get('paragraphs', []) if isinstance(unit, dict) else []
    if not isinstance(paragraphs, list) or not all(isinstance(p, str) for p in paragraphs):
        return []
    passage = ' '.join(paragraphs)
    sentences = [part for part in re.split(r'[.!?]+(?:\s+|$)', passage) if part.strip()]
    lengths = [len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", part)) for part in sentences]
    upper = config['reading_words']['min'] >= 320
    issues = []
    if lengths and (sum(lengths)/len(lengths) > (25 if upper else 21) or max(lengths) > (48 if upper else 40)):
        issues.append('Sentences are too dense for this age; use varied, shorter sentences and concrete examples.')
    if re.search(r'\b(?:researchers? (?:found|proved|frequently cite)|studies (?:show|prove|suggest)|peer-reviewed studies|research (?:shows|proves))\b', passage, re.I):
        issues.append('Remove vague research authority. Explain well-established facts directly; do not invent studies, findings or statistics.')
    if re.search(r'\b(?:completely|entirely|totally) eliminates? (?:the )?risk', passage, re.I):
        issues.append('Replace absolute safety promises with a precise statement of which hazard is reduced.')
    if re.search(r'\b(?:town|village|city) of [A-Z][a-z]+', passage) and not re.search(r'\b(?:fictional|imaginary|imagine)\b', passage, re.I):
        issues.append('Identify an invented town/event example explicitly as fictional; remove unsupported real-world performance statistics.')
    if re.search(r'\bbully(?:ing|ies)\b', passage, re.I):
        if re.search(r'(?:must|has to|needs to).*?repeat|happen.*?repeatedly', passage, re.I) and not re.search(r'potential|could happen again|may happen again', passage, re.I):
            issues.append('Bullying involves a power imbalance and repeated behavior OR the potential to repeat; do not require completed repetition.')
        if re.search(r'(?:four|three|\d)[ -]step|step (?:one|two|three|1|2|3)', passage, re.I) and re.search(r'witness|evidence|notes|write', passage, re.I):
            issues.append('Seek trusted adult help promptly. Never make finding a witness, collecting evidence or writing notes a prerequisite for reporting. Optional documentation comes after seeking help and only when safe.')
    return issues


def repair_unit_quality(raw, config, label):
    """Rewrite only flagged passages, then let existing evidence repair realign questions."""
    issues = passage_quality_issues(raw, config)
    if not issues:
        return raw
    retained = deepcopy(raw)
    def validate_passage(result):
        """Accept an age-accessible rewrite that preserves topic and bounded length."""
        if not isinstance(result, dict):
            raise ValueError('Return paragraphs as a JSON object')
        paragraphs = result.get('paragraphs')
        if not isinstance(paragraphs, list) or not 3 <= len(paragraphs) <= 4:
            raise ValueError('Return three or four complete paragraphs')
        revised = deepcopy(retained)
        revised['paragraphs'] = [bounded(p, 'Paragraph', 1300) for p in paragraphs]
        if passage_quality_issues(revised, config):
            raise ValueError('; '.join(passage_quality_issues(revised, config)))
        if not config['reading_words']['min'] <= passage_word_count(paragraphs) <= config['reading_words']['max']:
            raise ValueError(passage_length_feedback(paragraphs, config))
        return revised
    prompt = ('Rewrite ONLY the passage for elementary students. Preserve its substantive topic and '
              'supported facts needed by the five questions; keep supporting quotes where possible. Remove unsupported assertions even if a question currently depends on them: the following evidence repair will realign affected questions. Explicitly label invented examples as fictional. Replace academic '
              'jargon with clear language and define essential terms through examples. Do not add filler, '
              'invented research, statistics or new claims. Aim for sentences of 10-18 words, with varied '
              'lengths. Return {"paragraphs":[...]} in three or four paragraphs. Word range: '
              f"{config['reading_words']['min']}-{config['reading_words']['max']}. Problems: "
              + ' '.join(issues) + '\n' + json.dumps(raw))
    return ask_json(prompt, validate_passage, label+' accessibility repair', 3500,
                    response_schema=obj({'paragraphs':array(text(1300),3,4)}))


def balance_answer_positions(unit, reading_index, positions=None):
    """Relabel choices without changing their wording or the supported answer.

    A balanced shuffled schedule distributes 25 answers as 7/6/6/6.
    The key is built after this transformation.
    """
    revised = deepcopy(unit)
    for index, question in enumerate(revised['questions']):
        target = positions[index] if positions is not None else LETTERS[(reading_index*5+index) % 4]
        old = question['answer']
        if target != old:
            question['options'][target], question['options'][old] = question['options'][old], question['options'][target]
        question['answer'] = target
    return revised

def answer_position_schedule(count, rng=None):
    """Balance letters globally without runs or a single-letter question page."""
    rng = rng or random.SystemRandom()
    positions = [LETTERS[i % 4] for i in range(count)]
    for _ in range(200):
        rng.shuffle(positions)
        if all(len(set(positions[i:i+5])) >= min(3, len(positions[i:i+5])) for i in range(0,count,5)) and all(not positions[i] == positions[i+1] == positions[i+2] for i in range(count-2)):
            return positions
    # Guaranteed bounded fallback retains balance and all four letters per full set.
    offset = rng.randrange(4)
    return [LETTERS[(i+offset) % 4] for i in range(count)]


def illustration_scene(prompt):
    """Keep text-prone surfaces blank without asking an AI to inspect images."""
    scene = re.sub(r'\b(?:posters?|banners?|signage|signs?|noticeboards?|billboards?|whiteboards?|blackboards?|chalkboards?)\b',
                   'plain undecorated surfaces', prompt, flags=re.I)
    return ('Artwork composition: natural setting or simple plain walls; closed unmarked books only. '
            'Every surface is blank and undecorated. Show the action and relevant objects, not a decorated classroom display. '
            'No lettering, writing, labels, logos, banners, posters, signs or screens. Scene: '+scene)


def prepare_reading_unit(raw, config, label, *, retained=None):
    """Apply scoped repairs in dependency order before strict shared validation."""
    unit = repair_unit_quality(raw,config,label)
    unit = repair_unit_limits(unit,config,label)
    unit = repair_unit_evidence(unit,label)
    unit = repair_unit_text(unit,label,retained=retained)
    return validate_unit(unit,config,retained=retained)


def unit_schema():
    """Request content only; Python owns every printable layout and answer label."""
    question = obj({'prompt':text(120), 'skill':enum(SKILLS),
        'options':obj({letter:text(55) for letter in LETTERS}), 'answer':enum(LETTERS),
        'evidence':text(180, 'A verbatim supporting quote from the passage.'),
        'explanation':text(110, 'Explain briefly why the selected answer is supported.')})
    return obj({'title':text(80), 'paragraphs':array(text(1300),3,4),
        'image_prompt':text(650,'One meaningful scene supporting the reading; no letters or numbers.'),
        'questions':array(question,5,5)})


def validate_unit(raw, config, *, retained=None):
    """Check grade length, distinct choices, skills and direct passage evidence."""
    if not isinstance(raw, dict):
        raise ValueError('Reading unit must be a JSON object')
    unit = deepcopy(raw)
    if retained is not None:
        for key in ('title','image_prompt'):
            if unit.get(key) != retained[key]:
                raise ValueError('Comprehension review must preserve the title and image prompt')
    unit['title'] = bounded(unit.get('title'),'Title',80)
    paragraphs = unit.get('paragraphs')
    if not isinstance(paragraphs,list) or not 3 <= len(paragraphs) <= 4:
        raise ValueError('Reading passage needs 3-4 paragraphs')
    unit['paragraphs'] = [bounded(p,'Paragraph',1300) for p in paragraphs]
    passage = ' '.join(unit['paragraphs'])
    count = passage_word_count(unit['paragraphs'])
    low, high = config['reading_words']['min'], config['reading_words']['max']
    if not low <= count <= high:
        raise ValueError(passage_length_feedback(unit['paragraphs'],config))
    unit['image_prompt'] = bounded(unit.get('image_prompt'),'Illustration prompt',650)
    questions = unit.get('questions')
    if not isinstance(questions,list) or len(questions) != 5:
        raise ValueError('Each reading needs exactly five multiple-choice questions')
    seen, skills = set(), []
    for number, question in enumerate(questions,1):
        if not isinstance(question,dict):
            raise ValueError('Each question must be an object')
        question['prompt'] = bounded(question.get('prompt'),f'Question {number}',120)
        normalized = ' '.join(question['prompt'].lower().split())
        if normalized in seen:
            raise ValueError('Comprehension questions must be distinct')
        seen.add(normalized)
        if re.match(r'^(draw|trace|sort|count|calculate|design|colour|color)\b',normalized):
            raise ValueError('Use reading comprehension questions, not picture puzzles or arithmetic tasks')
        if question.get('skill') not in SKILLS:
            raise ValueError('Use a supported reading-comprehension skill')
        skills.append(question['skill'])
        options = question.get('options')
        if not isinstance(options,dict) or set(options) != set(LETTERS):
            raise ValueError('Every question needs exactly A, B, C and D options')
        question['options'] = {letter:bounded(options[letter],f'Question {number}, option {letter}',55) for letter in LETTERS}
        values = [' '.join(v.casefold().split()) for v in question['options'].values()]
        if len(set(values)) != 4 or any(v in {'all of the above','none of the above'} for v in values):
            raise ValueError('Options must be distinct, plausible choices without all/none of the above')
        if question.get('answer') not in LETTERS:
            raise ValueError('Answer must identify one of A-D')
        question['evidence'] = bounded(question.get('evidence'),'Supporting quotation',180)
        if not excerpt_in_passage(question['evidence'],unit['paragraphs']):
            raise ValueError(f'Question {number}: every answer needs a verbatim supporting quote copied from the passage; do not paraphrase')
        question['explanation'] = bounded(question.get('explanation'),f'Question {number} answer explanation',110)
    if len(set(skills)) < 3 or skills.count('detail') > 2 or 'inference' not in skills:
        raise ValueError('Include inference and at least three skills; no more than two literal-detail questions')
    if config['reading_words']['min'] >= 320 and not set(skills) & {'author_purpose','text_structure','comparison'}:
        raise ValueError('Grades 5-6 need an author-purpose, text-structure or comparison question')
    return unit



def workbook_colors(config, number):
    """Give each reading pair a coordinated, print-friendly color identity."""
    palettes = (('#166D88','#E0F2F7','#E88B35','#FFF0DA'),
                ('#AA4338','#FCECE7','#377E80','#E4F3EF'),
                ('#70529B','#F0E9FA','#C78629','#FFF1D9'),
                ('#267357','#E2F3E9','#BC6748','#FCEDE3'),
                ('#245EA0','#E5EFFB','#AF6041','#FCECDF'))
    accent, wash, secondary, alternate = palettes[(number-1) % len(palettes)]
    if config['student_font_pt'] < 12:
        # Upper grades retain color with calmer large-area fills.
        wash, alternate = '#F1F4F8', '#F8F1E8'
    return accent, wash, secondary, alternate


def render_cover(plan, grade_band, config, reading_count, *, scene_prompt=None):
    """Compose a concise branded cover dominated by uncropped artwork."""
    esc = html.escape
    accent, wash, secondary, alternate = workbook_colors(config,1)
    grade = grade_band.replace('th','').replace('rd','').replace('-','–')
    cover_html = (
        f'<h1 style="font-size:27pt;line-height:1.1;color:{accent};margin:0 0 3mm;'
        f'padding:3mm;background-color:{wash};border-radius:5mm;border-bottom:1.5mm solid {secondary}">{esc(plan["title"])}</h1>'
        f'<p style="font-size:14pt;margin:0 0 3mm;padding:2mm;background-color:{wash};'
        f'color:{accent};font-weight:bold">Grades {esc(grade)} • Reading Comprehension</p>'
        f'<div style="background-color:{alternate};padding:2mm;margin:0 0 3mm;border-radius:8mm;text-align:center">'
        '<img data-asset="cover" style="width:176mm;height:160mm"/></div>'
        f'<p style="font-size:12pt;line-height:1.2;padding:3mm;margin:0;background-color:{wash};'
        f'border-left:2mm solid {secondary};color:{accent};font-weight:bold">'
        f'{reading_count} readings • {reading_count*5} questions • Answer key</p>')
    scene = scene_prompt or plan.get('topics', ['A classroom reading scene'])[0]
    return dict(title=plan['title'],html=cover_html,cover_background='curved_color',images=[dict(id='cover',
        prompt='ART ONLY: '+illustration_scene(scene)+' Original polished editorial scene, large clear focal subject. '
               'No lettering, words, typography, symbols used as writing, titles or logos. '
               'No poster or book-cover text. For cultural topics use accurate relevant objects or settings, '
               'not generic costumes, feather headdresses or pan-cultural mascots. Coordinated vivid colors.')])


def render_unit(unit, number, config):
    """Render illustrated readings and spacious QCM pages with a shared answer model."""
    esc = html.escape
    font = config['student_font_pt']
    accent, wash, secondary, alternate = workbook_colors(config,number)
    heading = f'font-size:17pt;line-height:1.12;color:{accent};background-color:{wash};margin:0 0 3mm;padding:2mm;border-bottom:1mm solid {secondary}'
    plain = f'font-size:{font}pt;line-height:1.24;margin:0 0 3mm'
    title = unit['title']
    body = f'<p style="{plain};color:{accent};font-weight:bold">READING {number} • INFORMATIONAL TEXT</p>'
    body += f'<h1 style="{heading}">{esc(title)}</h1>'
    body += f'<p style="{plain}">Name: __________________________  Date: ______________</p>'
    # A square illustration retains its entire composition, without a thin banner
    # letterboxing it into a tiny central thumbnail or cropping important details.
    art_size = 86 if font >= 12 else 76
    # Pair the opening paragraph with the square art instead of spending its
    # neighboring column on generic study tips. This frees passage space without
    # shrinking illustrations, cutting content or reducing the student font.
    body += (f'<table style="width:180mm;border-spacing:0;margin:0 0 2mm"><tbody><tr>'
             f'<td style="width:{art_size+5}mm;padding:0 5mm 0 0">'
             f'<img data-asset="reading_{number}" style="width:{art_size}mm;height:{art_size}mm"/></td>'
             f'<td style="padding:2mm;background-color:{wash};border-top:1mm solid {secondary};vertical-align:top">'
             f'<p style="{plain};color:{accent};font-weight:bold;margin:0 0 2mm">Read with a purpose</p>'
             f'<p style="{plain};margin:0"><strong style="color:{accent}">1.</strong> {esc(unit["paragraphs"][0])}</p>'
             '</td></tr></tbody></table>')
    body += ''.join(f'<p style="{plain}"><strong style="color:{accent}">{index}.</strong> {esc(paragraph)}</p>' for index,paragraph in enumerate(unit['paragraphs'][1:],2))
    body += f'<p style="{plain};color:{accent}">Continue to the five questions on the next page.</p>'
    # Art has a full square footprint; the legacy worksheet quota is inappropriate
    # for a 420-word reading. Its physical size is fixed and tested instead.
    reading = dict(title=title,html=body,images=[dict(id=f'reading_{number}',prompt=illustration_scene(unit['image_prompt']))],
        answers='',page_type='reading',reading_unit=number,
        quality_profile=dict(minimum_text_pt=font,visual_area_mm2=0))
    quiz = f'<p style="{plain};color:{accent};font-weight:bold">READING {number} • CHECK YOUR UNDERSTANDING</p>'
    quiz += f'<h1 style="{heading}">{esc(title)}</h1>'
    quiz += f'<p style="{plain}">Name: __________________________  Date: ______________</p>'
    quiz += f'<p style="{plain}">Circle one answer for each question. Use details from Reading {number}.</p>'
    for index, question in enumerate(unit['questions'],1):
        quiz += f'<section style="min-height:31mm;margin:0 0 3mm;padding:2.5mm;background-color:{wash if index % 2 else alternate};border-left:1mm solid {accent if index % 2 else secondary}">'
        quiz += f'<p style="{plain};font-weight:bold;margin:0 0 1.5mm">{index}. {esc(question["prompt"])}</p>'
        for letter in LETTERS:
            quiz += (f'<p style="font-size:{font}pt;line-height:1.2;margin:0 0 1mm">'
                     f'<strong>({letter})</strong> {esc(question["options"][letter])}</p>')
        quiz += '</section>'
    question_page = dict(title=title+' - QCM',html=quiz,images=[],page_type='qcm',reading_unit=number,
        answers=' '.join(f'{i}. {q["answer"]}: {q["explanation"]}' for i,q in enumerate(unit['questions'],1)),
        answer_items=[dict(number=i,answer=q['answer'],explanation=q['explanation']) for i,q in enumerate(unit['questions'],1)],
        quality_profile=dict(minimum_text_pt=font,visual_area_mm2=0))
    try:
        check_page(reading,font)
    except ValueError as exc:
        raise ValueError(f'Reading passage page: {exc}') from exc
    try:
        check_page(question_page,font)
    except ValueError as exc:
        if not str(exc).startswith('Design overflow:'):
            raise
        # Long prompts/choices can wrap beyond the generous default card height.
        # Recompose choices into two rows, preserving their A-D reading order and
        # every word. Never repair fit by changing answers or reducing font size.
        compact = quiz[:quiz.index('<section')]
        for index, question in enumerate(unit['questions'],1):
            compact += f'<section style="margin:0 0 2mm;padding:2mm;background-color:{wash if index % 2 else alternate};border-left:1mm solid {accent if index % 2 else secondary}">'
            compact += f'<p style="{plain};font-weight:bold;margin:0 0 1.5mm">{index}. {esc(question["prompt"])}</p>'
            compact += '<table style="width:100%;border-spacing:0;table-layout:fixed"><tbody>'
            for row in ('AB','CD'):
                compact += '<tr>'
                for letter in row:
                    compact += (f'<td style="width:50%;padding:0 2mm 1mm 0"><p style="font-size:{font}pt;line-height:1.2;margin:0">'
                                f'<strong>({letter})</strong> {esc(question["options"][letter])}</p></td>')
                compact += '</tr>'
            compact += '</tbody></table></section>'
        question_page['html'] = compact
        try:
            check_page(question_page,font)
        except ValueError as fallback_error:
            raise ValueError(f'QCM question page: {fallback_error}') from fallback_error
    return reading, question_page


def generate_reading_pack(theme, grade_band, grade_config, *, source_context=None, book_title=None):
    """Generate paired readings/QCMs, a branded cover and one final answer sheet."""
    require_active_grade(grade_band)
    config = grade_config[grade_band]
    if book_title is not None:
        book_title = bounded(book_title,'Calendar keyword title',52)
    count = config['activity_pages']
    if type(count) is not int or count < 2 or count % 2:
        raise ValueError('Reading format needs an even activity_pages count: one passage and one QCM page per unit')
    topics_prompt = f'''Plan {count//2} DISTINCT original informational readings for {grade_band}.
Theme: {theme}. Inspiration/context: {source_context or theme}.
Selected keyword title: {book_title or 'Choose an original short title'}.
If a keyword title is supplied, use it VERBATIM and center every reading on that keyword's
context. The product remains reading comprehension: for craft/activity/bulletin-board
keywords, readings explore those processes and purposes; do not promise hands-on templates
or a display kit. Compare relevant perspectives, procedures and examples without filler.
Use the context as inspiration; do not copy any referenced product. The format is READING + QCM ONLY.
The product is a READING COMPREHENSION WORKBOOK. Its title must describe the complete set of
readings; do not advertise a weight/math challenge, experiment, game or hands-on project that is not
actually included. When no keyword title was supplied, choose a SHORT cover title of 3-7 words.
A supplied keyword title is exact and may have fewer words. All titles are at most 52 characters.
Do not generate a cover description or overview.
Return title and topics: exactly {count//2} short descriptions with different substantive learning goals.
Make the theme central to every reading. Plan concrete knowledge children can use, not
abstract articles about how researchers or authors work. Choose five genuinely different angles:
real-world explanation, an everyday example, a practical process, comparison, and a thoughtful problem.
Each topic must stand alone; avoid repeating the same message across all five readings. Avoid contrived arithmetic, picture counting, matching, sorting,
mazes, generic reflection, and superficial topic changes. No teacher guide. For cultures, avoid stereotypes,
monolithic claims and invented histories; represent named communities accurately and respectfully.
For science use correct explanations; never confuse size with mass, weight or strength.
Grades 3-4: accessible informational reading, vocabulary in context, main idea, inference, cause/effect.
Grades 5-6: more detailed texts, reasoning about evidence, author's purpose, text structure and inference.'''
    schema = obj({'title':text(52),'topics':array(text(350),count//2,count//2)})
    def validate_plan(raw):
        """Keep the plan concise and require a distinct topic for every pair."""
        if not isinstance(raw,dict) or not isinstance(raw.get('topics'),list) or len(raw['topics']) != count//2:
            raise ValueError('Return one distinct topic for each reading unit')
        topics = [bounded(t,'Topic',350) for t in raw['topics']]
        if len(set(t.casefold() for t in topics)) != len(topics):
            raise ValueError('Reading topics must be distinct')
        return dict(title=book_title or bounded(raw.get('title'),'Short cover title',52),topics=topics)
    plan = ask_json(topics_prompt,validate_plan,'Reading plan',3000,response_schema=schema)
    low, high = config['reading_words']['min'],config['reading_words']['max']
    def make_unit(index):
        """Generate and independently review one reading with its five questions."""
        prompt = f'''Write an ORIGINAL {grade_band} informational reading and five multiple-choice questions.
Theme: {theme}. Book keyword/title: {plan['title']}. Topic: {plan['topics'][index]}. User context: {source_context or theme}.
Other unit topics (avoid repetition): {json.dumps(plan['topics'])}
Passage: {low}-{high} words; aim for {(low+high)//2} words in four balanced paragraphs of about {(low+high)//8} words. Passage words exclude questions and choices. {config['reading_guidance']}
Write for actual children aged 8-10 (grades 3-4) or 10-12 (grades 5-6), not university students.
Use concrete people, places, objects and actions. Aim for average sentences of 10-18 words;
explain essential domain terms in context. Avoid dense nominalizations, academic filler and vague
research language such as "researchers found", "studies show" or "peer-reviewed findings".
State well-established facts only. No invented study results, unsupported dates/statistics,
fabricated quotations or cultural generalizations. Clearly label any invented example as a fictional scenario.
For bullying: never blame targets, recommend confronting a bully alone, or frame a power imbalance as
ordinary peer conflict requiring peer mediation. Define bullying using a power imbalance plus repetition OR potential repetition. A single disagreement is not automatically bullying. Seek trusted adult help promptly; witnesses or notes are NEVER required before reporting. Documentation is optional, after seeking help and only if safe. Do not invent a school's policy; label any example process fictional. Emphasize safe help from responsible trusted adults.
No babyish picture puzzles, arithmetic calculations, drawing, sorting, mazes or teacher instructions.
Questions: five, with four distinct plausible choices A-D, exactly ONE defensible correct choice.
Use at least three reading skills, including inference; at most two literal-detail questions. Grades 5-6 must include author_purpose, text_structure or comparison. Vary correct answer positions across A-D.
Ask about the supplied text only; never require inspecting an AI illustration. Avoid ambiguous answers,
trick questions, all/none of the above, and distractors distinguishable only by length or absurdity.
Wrong choices must be plausible misunderstandings of this SAME passage, parallel in grammar and
roughly similar in length. Avoid silly unrelated choices and giveaway absolutes. Do not simply
repeat the exact answer sentence as the correct option. Write one supported answer first, then
three specific misconceptions. Test EACH choice against the exact question: no two choices may
express the same answer in different words, and a true passage fact is not a distractor if it also
answers the question. Replace the whole question and all four choices when their meanings overlap.
Inference requires connecting at least two details to reach an unstated conclusion. Do not label a
sentence explicitly stated in the passage as inference. Wrong options should relate to the topic and
reflect a specific misunderstanding, rather than magic, silly actions, unrelated objects or absolutes.
Do not invent a historical cause just to make a cause/effect question. Distinguish supported history
from folklore and avoid presenting legends as evidence of ancient practices. Avoid sweeping safety
claims such as "completely eliminates risk". Examples with invented towns, events or data MUST be
explicitly identified in the passage as fictional. Never state invented battery lifetimes or costs as
universal facts. Avoid contrived fractions or measurements with unspecified quantities.
Provide a verbatim quote from the passage and a concise explanation for every correct answer.
Question prompts <=120 characters; choices <=55 (aim for 35-45); explanations <=110 (aim for 60-90); quotes <=180. Use complete concise sentences.
Include one relevant original image prompt <=650 chars: show a large clear focal subject with purposeful contextual details, vivid coordinated colors and a polished textbook illustration composition, no wording or numbers; no guessing exact image counts.
For cultural illustrations prefer specific relevant objects, environments or contemporary learning scenes; avoid generic historical costumes, feather headdresses and pan-cultural mascots. Never include lettering. Prefer outdoors, natural settings or plain undecorated walls. Do not include posters, banners, signs, chalkboards, whiteboards, screens or open printed books; use closed unmarked books if needed.
Return content JSON only, never HTML/CSS. Fields: title, paragraphs, image_prompt, questions.'''
        unit = ask_json(prompt,lambda raw:prepare_reading_unit(raw,config,f'Reading {index+1}'),
                        f'Reading {index+1}',6000,response_schema=unit_schema())
        review_prompt = ('Independently solve and proofread these five reading-comprehension questions. '
            'Keep title and image_prompt VERBATIM. Return the complete unit. Correct factual errors in the passage if needed while preserving its topic and grade word range. '
            'Repair questions, options, answer letters, quotes or explanations if needed. '
            'Each question must have precisely one supported answer, plausible but incorrect distractors, '
            'correct answer-letter alignment and valid evidence. Solve WITHOUT reading the provided answer first, then compare. Check EACH choice against the exact prompt, including synonymous options and true facts that also answer it. If two choices are defensible, replace the entire question and ALL four options while retaining its reading skill; do not merely change the key letter or one word. Reject a second defensible choice and replace absurd or obviously unrelated distractors with plausible text-based misconceptions. Check factual accuracy and define essential vocabulary. Read the passage as an actual elementary child, not an academic researcher: rewrite dense jargon, remove vague research claims, and retain concrete useful knowledge. '
            'Use a skeptical editorial review: challenge every historical cause, numerical claim, absolute safety statement and environmental generalization. Remove any claim you cannot confidently support instead of making its falsehood the basis of a question. Label invented examples explicitly as fictional. Check grammar, units and logical quantities. An inference answer must NOT already be explicitly stated. Distractors must be plausible errors in understanding this same topic; rewrite silly or unrelated choices. Preserve the grade-appropriate skill mix and all five questions. This is text review only, not image review.\n'
            +json.dumps(unit))
        def validate_review(raw):
            """Validate review content and retry wording if the fixed page cannot fit."""
            reviewed = prepare_reading_unit(raw,config,f'Comprehension review {index+1}',retained=unit)
            try:
                pair = render_unit(reviewed,index+1,config)
            except ValueError as exc:
                raise ValueError('Reading/QCM page cannot fit. Shorten sentences and choices while preserving '
                                 f'the grade word range, five questions and evidence: {exc}') from exc
            return reviewed, pair
        reviewed, _ = ask_json(review_prompt,validate_review,
            f'Comprehension review {index+1}',6000,response_schema=unit_schema())
        verified = verify_question_answers(reviewed,config,f'Reading {index+1}',ask=ask_json)
        return verified, render_unit(verified,index+1,config)
    workers = text_worker_limit(int_setting('DESIGN_WORKERS',3,1,4))
    generated = ordered_parallel(make_unit,range(count//2),workers)
    positions = answer_position_schedule(count//2*5)
    generated = [(balance_answer_positions(unit,index,positions[index*5:index*5+5]),pair) for index,(unit,pair) in enumerate(generated)]
    pages = [page for index,(unit,_) in enumerate(generated) for page in render_unit(unit,index+1,config)]
    cover = render_cover(plan,grade_band,config,count//2,scene_prompt=generated[0][0]['image_prompt'])
    pack = dict(title=plan['title'],theme=theme,grade_band=grade_band,
        content_format='reading_qcm',resource_type='activity_pack',art_direction=config['illustration_style'],character_description='',
        cover=cover,pages=pages,reading_units=[unit for unit,_ in generated],
        content_checks=dict(status='passed',review='text_only',reading_units=count//2,questions=count//2*5,
                            checks=['grade_word_range','accessibility_signals','distinct_choices','passage_evidence','skill_mix','blind_answer_verification','balanced_answer_positions','print_bounds']))
    check_page(cover,config['student_font_pt'],cover=True)
    preflight_pack(pack,config)
    return pack

