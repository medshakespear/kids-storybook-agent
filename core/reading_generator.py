"""Generate grade-appropriate reading passages and evidence-backed multiple-choice questions."""
from copy import deepcopy
import html
import re
import json
import unicodedata

from core.creative_generator import ask_json
from core.creative_layout import check_page, preflight_pack
from core.grade_policy import require_active_grade
from core.providers import text_worker_limit
from core.response_schemas import array, enum, obj, text
from core.runtime import int_setting, ordered_parallel

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
        if not low <= passage_word_count(paragraphs) <= high:
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
            prompt = ('Repair ONLY the passage length in this retained reading unit. '
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
        question['explanation'] = bounded(question.get('explanation'),'Answer explanation',110)
    if len(set(skills)) < 3 or skills.count('detail') > 2 or 'inference' not in skills:
        raise ValueError('Include inference and at least three skills; no more than two literal-detail questions')
    if config['reading_words']['min'] >= 320 and not set(skills) & {'author_purpose','text_structure','comparison'}:
        raise ValueError('Grades 5-6 need an author-purpose, text-structure or comparison question')
    return unit


def render_unit(unit, number, config):
    """Render a reading page and QCM page from the same reviewed content object."""
    esc = html.escape
    font = config['student_font_pt']
    accent, wash = config['accent'], config['wash']
    heading = f'font-size:20pt;color:{accent};background-color:{wash};padding:3mm;margin:0 0 3mm'
    plain = f'font-size:{font}pt;line-height:1.3;margin:0 0 3mm'
    image_height = 62 if font >= 12 else 48
    title = unit['title']
    body = f'<h1 style="{heading}">{esc(title)}</h1><p style="{plain}">Reading {number} | Name: ____________________</p>'
    body += f'<img data-asset="reading_{number}" style="width:175mm;height:{image_height}mm;margin:0 0 3mm"/>'
    body += ''.join(f'<p style="{plain}">{esc(paragraph)}</p>' for paragraph in unit['paragraphs'])
    body += f'<p style="{plain};color:{accent}">Next: use this passage to answer the five questions.</p>'
    reading = dict(title=title,html=body,images=[dict(id=f'reading_{number}',prompt=unit['image_prompt'])],
        answers='',page_type='reading',reading_unit=number,
        quality_profile=dict(minimum_text_pt=font,visual_area_mm2=config['visual_area_mm2']))
    quiz = f'<h1 style="{heading}">{esc(title)}: Read and Choose</h1>'
    quiz += f'<p style="{plain}">Name: ____________________ | Choose one answer for each question. Use Reading {number}.</p>'
    for index, question in enumerate(unit['questions'],1):
        quiz += f'<section style="margin:0 0 4mm;padding:2mm;border:0.5mm solid {accent};border-radius:3mm">'
        quiz += f'<p style="{plain};font-weight:bold;margin:0 0 2mm">{index}. {esc(question["prompt"])}</p>'
        for letter in LETTERS:
            quiz += (f'<p style="font-size:{font}pt;line-height:1.2;margin:0 0 1mm">'
                     f'<strong>{letter}.</strong> {esc(question["options"][letter])}</p>')
        quiz += '</section>'
    question_page = dict(title=title+' - QCM',html=quiz,images=[],page_type='qcm',reading_unit=number,
        answers=' '.join(f'{i}. {q["answer"]}: {q["explanation"]}' for i,q in enumerate(unit['questions'],1)),
        quality_profile=dict(minimum_text_pt=font,visual_area_mm2=0))
    # These checks apply the same real A4 bounds and typography checks, without
    # demanding artwork on a page whose purpose is text-based comprehension.
    check_page(reading,font)
    check_page(question_page,font)
    return reading, question_page


def generate_reading_pack(theme, grade_band, grade_config, *, source_context=None):
    """Generate paired readings/QCMs, a branded cover and one final answer sheet."""
    require_active_grade(grade_band)
    config = grade_config[grade_band]
    count = config['activity_pages']
    if type(count) is not int or count < 2 or count % 2:
        raise ValueError('Reading format needs an even activity_pages count: one passage and one QCM page per unit')
    topics_prompt = f'''Plan {count//2} DISTINCT original informational readings for {grade_band}.
Theme: {theme}. Inspiration/context: {source_context or theme}.
Use the context as inspiration; do not copy any referenced product. The format is READING + QCM ONLY.
Return title, overview, and topics: exactly {count//2} short descriptions with different substantive learning goals.
Make the theme central to every reading. Avoid contrived arithmetic, picture counting, matching, sorting,
mazes, generic reflection, and superficial topic changes. No teacher guide. For cultures, avoid stereotypes,
monolithic claims and invented histories; represent named communities accurately and respectfully.
For science use correct explanations; never confuse size with mass, weight or strength.
Grades 3-4: accessible informational reading, vocabulary in context, main idea, inference, cause/effect.
Grades 5-6: more detailed texts, reasoning about evidence, author's purpose, text structure and inference.'''
    schema = obj({'title':text(80),'overview':text(350),'topics':array(text(350),count//2,count//2)})
    def validate_plan(raw):
        """Keep the plan concise and require a distinct topic for every pair."""
        if not isinstance(raw,dict) or not isinstance(raw.get('topics'),list) or len(raw['topics']) != count//2:
            raise ValueError('Return one distinct topic for each reading unit')
        topics = [bounded(t,'Topic',350) for t in raw['topics']]
        if len(set(t.casefold() for t in topics)) != len(topics):
            raise ValueError('Reading topics must be distinct')
        return dict(title=bounded(raw.get('title'),'Pack title',80),overview=bounded(raw.get('overview'),'Overview',350),topics=topics)
    plan = ask_json(topics_prompt,validate_plan,'Reading plan',3000,response_schema=schema)
    low, high = config['reading_words']['min'],config['reading_words']['max']
    def make_unit(index):
        """Generate and independently review one reading with its five questions."""
        prompt = f'''Write an ORIGINAL {grade_band} informational reading and five multiple-choice questions.
Theme: {theme}. Topic: {plan['topics'][index]}. User context: {source_context or theme}.
Other unit topics (avoid repetition): {json.dumps(plan['topics'])}
Passage: {low}-{high} words; aim for {(low+high)//2} words in four balanced paragraphs of about {(low+high)//8} words. Passage words exclude questions and choices. {config['reading_guidance']}
State reliable facts only. Avoid unsupported dates/statistics, fabricated quotations or cultural generalizations.
No babyish picture puzzles, arithmetic calculations, drawing, sorting, mazes or teacher instructions.
Questions: five, with four distinct plausible choices A-D, exactly ONE defensible correct choice.
Use at least three reading skills, including inference; at most two literal-detail questions. Grades 5-6 must include author_purpose, text_structure or comparison. Vary correct answer positions across A-D.
Ask about the supplied text only; never require inspecting an AI illustration. Avoid ambiguous answers,
trick questions, all/none of the above, and distractors distinguishable only by length or absurdity.
Provide a verbatim quote from the passage and a concise explanation for every correct answer.
Question prompts <=120 characters; choices <=55; explanations <=110; quotes <=180.
Include one relevant original image prompt <=650 chars, no wording or numbers; no guessing exact image counts.
Return content JSON only, never HTML/CSS. Fields: title, paragraphs, image_prompt, questions.'''
        unit = ask_json(prompt,lambda raw:validate_unit(repair_unit_evidence(repair_unit_limits(raw,config,f'Reading {index+1}'),f'Reading {index+1}'),config),
                        f'Reading {index+1}',6000,response_schema=unit_schema())
        review_prompt = ('Independently solve and proofread these five reading-comprehension questions. '
            'Keep title and image_prompt VERBATIM. Return the complete unit. Correct factual errors in the passage if needed while preserving its topic and grade word range. '
            'Repair questions, options, answer letters, quotes or explanations if needed. '
            'Each question must have precisely one supported answer, plausible but incorrect distractors, '
            'correct answer-letter alignment and valid evidence. Check factual accuracy, grade suitability, vocabulary and inference against the passage. '
            'Preserve the grade-appropriate skill mix and all five questions. This is text review only, not image review.\n'
            +json.dumps(unit))
        def validate_review(raw):
            """Validate review content and retry wording if the fixed page cannot fit."""
            reviewed = validate_unit(repair_unit_evidence(repair_unit_limits(raw,config,f'Comprehension review {index+1}'),f'Comprehension review {index+1}'),config,retained=unit)
            try:
                pair = render_unit(reviewed,index+1,config)
            except ValueError as exc:
                raise ValueError('Reading/QCM page cannot fit. Shorten sentences and choices while preserving '
                                 f'the grade word range, five questions and evidence: {exc}') from exc
            return reviewed, pair
        return ask_json(review_prompt,validate_review,
            f'Comprehension review {index+1}',6000,response_schema=unit_schema())
    workers = text_worker_limit(int_setting('DESIGN_WORKERS',3,1,4))
    generated = ordered_parallel(make_unit,range(count//2),workers)
    pages = [page for _,pair in generated for page in pair]
    cover = dict(title=plan['title'],images=[dict(id='cover',prompt=f'Original editorial illustration about {theme}: {plan["overview"]}. No text or numbers.')],
        html=f'<h1 style="font-size:30pt;color:{config["accent"]};margin:0 0 5mm">{html.escape(plan["title"])}</h1>'
             f'<p style="font-size:16pt">Grades {html.escape(grade_band)} | Read and Choose</p>'
             f'<img data-asset="cover" style="width:175mm;height:100mm"/>'
             f'<p style="font-size:12pt">{html.escape(plan["overview"])}</p>'
             f'<p style="font-size:12pt">{count//2} readings | {count//2*5} multiple-choice questions | Answer key included</p>')
    pack = dict(title=plan['title'],overview=plan['overview'],theme=theme,grade_band=grade_band,
        content_format='reading_qcm',art_direction=config['illustration_style'],character_description='',
        cover=cover,pages=pages,reading_units=[unit for unit,_ in generated],
        content_checks=dict(status='passed',review='text_only',reading_units=count//2,questions=count//2*5,
                            checks=['grade_word_range','distinct_choices','passage_evidence','skill_mix','print_bounds']))
    check_page(cover,config['student_font_pt'],cover=True)
    preflight_pack(pack,config)
    return pack
