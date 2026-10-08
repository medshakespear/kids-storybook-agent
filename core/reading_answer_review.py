"""Blind text-only answer verification, with bounded repairs of faulty questions."""
from copy import deepcopy
import json
import logging
import re
import unicodedata

LOGGER = logging.getLogger(__name__)

from core.activity_generator import ActivityGenerationError
from core.response_schemas import array, enum, integer, obj, text


def choice_identity(value):
    """Compare recycled choices without punctuation, casing or Unicode differences."""
    return ' '.join(re.findall(r'\w+',unicodedata.normalize('NFKC',value).casefold()))


def verify_question_answers(unit, config, label, *, ask):
    """Solve without the supplied key, repair mismatches, and verify again.

    This is independent model-based semantic review, not external fact checking.
    No images are sent. Repairs cannot change the passage or unaffected questions.
    """
    from core.reading_generator import validate_unit, unit_schema, prepare_reading_unit
    current = deepcopy(unit)
    solution_schema = obj({'solutions': array(obj({
        'number': integer(1, 5), 'answer': enum(['A','B','C','D','NONE','AMBIGUOUS']),
        'reason': text(1000, 'Passage-based explanation; prefer at most 110 characters.'),
        'quality_issues': array(enum(['literal_inference','implausible_distractors']),0,2)
    }), 5, 5)})

    def validate_solutions(raw):
        """Require one explicitly numbered independent solution for every question."""
        solutions = raw.get('solutions') if isinstance(raw, dict) else None
        if not isinstance(solutions, list) or len(solutions) != 5:
            raise ValueError('Return five numbered solutions')
        found = {}
        for solution in solutions:
            if not isinstance(solution, dict):
                raise ValueError('Each solution must be an object')
            number = solution.get('number')
            if type(number) is not int or number not in range(1,6) or number in found:
                raise ValueError('Solution numbers must be exactly 1-5, each once')
            if solution.get('answer') not in ('A','B','C','D','NONE','AMBIGUOUS'):
                raise ValueError('Select A-D, NONE or AMBIGUOUS')
            issues = solution.get('quality_issues')
            if not isinstance(issues,list) or any(i not in ('literal_inference','implausible_distractors') for i in issues):
                raise ValueError('Return quality_issues as a list of supported defect labels, or []')
            reason = solution.get('reason')
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError('Review reason must be nonempty text')
            # Review diagnostics are not printed content. Preserve the full reason
            # for semantic repairs instead of rejecting or truncating a valid solve.
            reason = ' '.join(reason.split())
            found[number] = dict(answer=solution['answer'], reason=reason,quality_issues=issues)
        return found

    ambiguous_numbers, rejected = set(), {}
    for attempt in range(6):
        # The proposed key, explanations and supporting quotations are deliberately
        # absent. Otherwise a reviewer can rationalize an unrelated selected choice.
        blind = {'paragraphs': current['paragraphs'], 'questions': [
            {'number': n, 'prompt': q['prompt'], 'options': q['options'], 'skill':q['skill']}
            for n,q in enumerate(current['questions'],1)]}
        prompt = ('Solve these five reading questions using ONLY the passage and printed options. '
                  'No answer key is supplied. Select NONE when no option answers the question, and '
                  'AMBIGUOUS when two or more options are defensible. Never select a merely related '
                  'option or borrow the answer from another question. Also audit question quality: '
                  'literal_inference means a question labeled inference merely asks for an explicitly stated fact, '
                  'instead of combining details into an unstated conclusion. implausible_distractors means '
                  'wrong choices are unrelated, absurd, obvious giveaways or cannot plausibly reflect a misunderstanding of this passage. '
                  'Judge real defects, not stylistic preferences. A short but sensible same-topic misunderstanding '
                  'is a valid distractor. literal_inference applies ONLY when skill is inference. '
                  'Return quality_issues [] when neither defect exists; otherwise use those exact labels. '
                  'When flagging a defect, explain its specific cause in reason. '
                  'Return solutions with number, quality_issues, '
                  'answer and a brief reason of at most 110 characters (aim for 60-90). Do not invent missing options.\n'+json.dumps(blind))
        solutions = ask(prompt, validate_solutions, label+' blind answer verification', 2200,
                        response_schema=solution_schema)
        faults = {n: result for n,result in solutions.items()
                  if result['answer'] != current['questions'][n-1]['answer'] or result['quality_issues']}
        if not faults:
            for number, result in solutions.items():
                # The existing explanation already passed the printable contract.
                # A verbose reviewer reason must not force a new API request or
                # overflow the shared answer-key page.
                if len(result['reason']) <= 110:
                    current['questions'][number-1]['explanation'] = result['reason']
            return validate_unit(current,config)
        ambiguous_numbers.update(n for n,result in faults.items() if result['answer']=='AMBIGUOUS')
        for number in faults:
            rejected.setdefault(number,[]).append(deepcopy(current['questions'][number-1]))
        max_reviews = 6 if ambiguous_numbers else 4
        fresh = attempt >= 2 or any(n in ambiguous_numbers for n in faults)
        details = '; '.join(f"Q{n}: expected {current['questions'][n-1]['answer']}, reviewer {r['answer']}, issues {r['quality_issues']}: {r['reason']}" for n,r in sorted(faults.items()))
        LOGGER.warning('%s: answer-check defects (pass %s/%s): %s',label,attempt+1,max_reviews,details)
        if attempt+1 >= max_reviews:
            raise ActivityGenerationError(f'{label}: answer verification still fails after {max_reviews-1} bounded repair/replacement attempts; {details}; PDF not published')
        retained = deepcopy(current)

        def validate_repairs(raw):
            """Freeze passage and unaffected questions while validating complete repairs."""
            repairs = raw.get('repairs') if isinstance(raw,dict) else None
            if not isinstance(repairs,list) or len(repairs) != len(faults):
                raise ValueError('Repair exactly the flagged question numbers')
            candidate, seen = deepcopy(retained), set()
            for repair in repairs:
                number = repair.get('number') if isinstance(repair,dict) else None
                if type(number) is not int or number not in faults or number in seen:
                    raise ValueError('Unknown or duplicate repaired question number')
                seen.add(number)
                candidate['questions'][number-1] = deepcopy(repair.get('question'))
            candidate = prepare_reading_unit(candidate,config,label+' repaired questions',retained=retained)
            if candidate['paragraphs'] != retained['paragraphs'] or any(candidate['questions'][i]!=q for i,q in enumerate(retained['questions']) if i+1 not in faults):
                raise ValueError('Question repair must preserve passage and every unaffected question')
            for number in faults:
                question = candidate['questions'][number-1]
                if question['skill'] != retained['questions'][number-1]['skill']:
                    raise ValueError('Keep each repaired question reading skill unchanged')
                if fresh and number in ambiguous_numbers:
                    history = rejected[number]
                    if choice_identity(question['prompt']) in {choice_identity(q['prompt']) for q in history}:
                        raise ValueError('Ambiguous-question replacement must use a new question stem, not the rejected stem')
                    banned = {choice_identity(option) for q in history for option in q['options'].values()}
                    if any(choice_identity(option) in banned for option in question['options'].values()):
                        raise ValueError('Ambiguous-question replacement must rewrite ALL four choices; do not recycle rejected options')
            return candidate

        repair_schema = obj({'repairs':array(obj({'number':integer(1,5),
                             'question':unit_schema()['properties']['questions']['items']}),len(faults),len(faults))})
        prompt = ('Repair ONLY these faulty comprehension questions: '+json.dumps(faults)+'. '
                  'Return repairs [{number,question}] containing complete question objects. Keep the '
                  'passage, title, illustration and every unaffected question unchanged. A selected '
                  'option must actually answer its own prompt and agree with its explanation. When '
                  'no correct choice exists, replace the faulty choice, not just the answer letter. '
                  'Repair flagged quality defects even if the answer letter was correct: inference must require a supported unstated conclusion; use plausible same-topic misunderstandings as distractors. Retain the grade skill mix. Copy real passage evidence. '
                  'Do not insert claims into the passage to justify a bad option.\n'+json.dumps(retained))
        repair_label = label+' answer repair'
        if fresh:
            # Do not keep editing an anchored bad question. Supply the passage and
            # accepted questions only, and require a genuinely new scoped question.
            source = {k:v for k,v in retained.items() if k!='questions'}
            source['accepted_questions']=[{'number':n,'question':q} for n,q in enumerate(retained['questions'],1) if n not in faults]
            source['replacement_requirements']=[{'number':n,'skill':retained['questions'][n-1]['skill'],'defect':result,
                **({'rejected_stems':[q['prompt'] for q in rejected[n]],'rejected_options':[option for q in rejected[n] for option in q['options'].values()]} if n in ambiguous_numbers else {})} for n,result in sorted(faults.items())]
            prompt = ('Write BRAND-NEW questions to replace ONLY the listed failing numbers. '
                      'Do not paraphrase the old question or repeat its flawed reasoning. For ambiguous questions, '
                      'use a DIFFERENT aspect of the frozen passage and rewrite ALL FOUR choices; none may repeat '
                      'a rejected stem or choice. Keep accepted questions unchanged. Every replacement must have exactly one supported '
                      'A-D answer and plausible but incorrect distractors. Check EACH choice against the exact question: '
                      'no synonyms of the correct answer, overlapping true claims, or two passage-supported answers. '
                      'Keep the specified reading skill: an inference combines at least two details into an unstated conclusion, '
                      'not a copied fact. Return repairs [{number,question}] with complete question objects. '
                      'Prompt <=120 characters, options <=55 (aim 35-45), explanation <=110 (aim 60-90), '
                      'evidence <=180 and copied verbatim. Never invent passage facts.\n'+json.dumps(source))
            repair_label = label+' fresh question replacement'
        current = ask(prompt,validate_repairs,repair_label,3500,response_schema=repair_schema)
    raise AssertionError('Unreachable answer-review state')
